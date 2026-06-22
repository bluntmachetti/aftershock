"""FastAPI web server for the Aftershock observatory.

Provides:
  - Run listing / detail / paged ticks (replays with world states)
  - Benchmark results (/api/bench)
  - Live run lifecycle: POST /api/live, WS /ws/live, POST /api/live/inject
  - Static serving of web/dist when present

Scenario packs (additive, task #4):
  - GET /api/scenarios            list (compact, ungated)
  - GET /api/scenarios/{id}       full pack incl. reference (ungated)
  - POST /api/live                gains optional scenario id; ticks becomes optional
  - run.json manifest carries a scenario block; /api/runs and /api/runs/{id} expose it

Security:
  - run_id validated against ^[A-Za-z0-9._-]+$ and resolved().is_relative_to(runs_root)
  - scenario id validated against ^[a-z0-9][a-z0-9-]*$ via the same traversal-guard pattern
  - Never formats exceptions into responses
  - limit parameters capped at 200
  - OBSERVATORY_TOKEN env var gates mutating POST endpoints (required when --host != 127.0.0.1)
  - CORSMiddleware restricts origins to OBSERVATORY_ORIGIN env var
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder, load_run
from aftershock.town.arms import build_arm
from aftershock.town.scenario import (
    ScenarioPack,
    load_scenario,
    scenario_tick_budget,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# Scenario id grammar (matches the dir name; same as town/scenario.py loader).
_SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# Subdirectory under runs_root that holds the curated society "episode" runs
# (e.g. runs/episodes/ep1-seed100-society). Their leaf names match _RUN_ID_RE but
# the slash-forbidding regex means they cannot be addressed as "episodes/ep1-…";
# _validate_run_id and _scan_runs fall back to / list this subdir so the episodes
# are reachable as plain run_ids (ep1-seed100-society) without filesystem
# symlinks that would need re-wiring per deployment.
_EPISODES_SUBDIR = "episodes"
_MAX_TICKS_LIVE = 120
_MAX_LIMIT = 200
_DEFAULT_SYNTHETIC_TICKS = 30
# Wall-clock pause between streamed ticks in a LIVE run, so a fast (scripted)
# stream plays at a watchable cadence instead of bursting all ticks at once.
# Presentation-only: passed to Engine.run(inter_tick_delay_s=...) on the live path;
# cli/bench/verify never set it, so determinism is unaffected. Tests neutralize it.
_LIVE_TICK_DELAY_S = 0.6
# Ambient demo loop (enabled by AFTERSHOCK_DEMO_MODE): back-to-back scripted runs that
# keep the public Live tab alive over the read-only WS without any client mutation. A
# manual operator run pre-empts the current ambient run; the loop resumes after it ends.
_AMBIENT_TICKS = 30
_AMBIENT_SEEDS = (42, 7, 13, 23, 57)
_AMBIENT_RESTART_DELAY_S = 4.0  # pause on the final scoreboard between ambient runs
_AMBIENT_POLL_S = 2.0  # re-check cadence while a manual run holds the floor
# Scenario tick budget (default + under-budget floor) comes from the shared
# town.scenario.scenario_tick_budget helper so the CLI and the live API agree.
_VALID_INJECT_KINDS = frozenset({"fire", "aftershock", "road_block"})
_MAX_PENDING_INJECTIONS = 50

# The LLM arms that need DASHSCOPE_API_KEY (society live/branch 503 without it).
# Module-level so /api/status, /api/live, and /api/counterfactual share one list.
_LLM_ARMS = ("solo", "swarm", "society")

# The canonical published 4-arm benchmark batch (bench/results/<dir>/). BenchTab
# headlines THIS batch — the +28 society-vs-swarm result the narration + evidence
# pack cite — rather than the newest-by-mtime one, so later research-ablation
# batches stay available via /api/bench but never headline the judge-facing view.
_CANONICAL_BENCH_DIR = "2026-06-11"

# Cached scripted-engine determinism check (GET /api/determinism). The verify
# re-run is ~seconds for the scripted arm; cache it per-process so the BenchTab
# badge is instant after the first hit. Reset only on server restart.
_DETERMINISM_SEED = 42
_DETERMINISM_TICKS = 60
_determinism_cache: dict[str, Any] | None = None
_determinism_lock: asyncio.Lock | None = None

# Per-pack caveat lines (DESIGN.md task #4, invariant 4 — chosen per pack so it never
# claims a category the pack's field_provenance does not support). A pack with a
# populated reference.missions carries a real latency baseline (dispatch pack); a pack
# without one is hazard-timing-only.
_CAVEAT_DISPATCH = "Demand: real · Latency baseline: real · Lives & outcomes: simulated model."
_CAVEAT_HAZARD_ONLY = "Hazard timing: real · Demand & outcomes: simulated model."


# ---------------------------------------------------------------------------
# Request/response models (module-level so FastAPI resolves them correctly)
# ---------------------------------------------------------------------------


class LiveRunRequest(BaseModel):
    arm: str
    seed: int
    # ticks is optional so the server can distinguish "omitted" (default 30 synthetic,
    # min(last timeline tick + 20, 120) for a scenario run) from an explicit 30.
    ticks: int | None = None
    aar: bool = False
    memory: bool = False
    # Optional scenario id; when set the world is built from the committed pack.
    scenario: str | None = None


class InjectRequest(BaseModel):
    kind: str
    district: str


class CounterfactualRequest(BaseModel):
    arm: str
    seed: int
    ticks: int
    at_tick: int
    kind: str
    target: str = ""
    params: dict[str, Any] = {}
    baseline_run_id: str | None = None
    # When the baseline was recorded from a scenario pack, the branch must rebuild
    # the SAME scenario world (else the prefix is not byte-identical). The client
    # passes the baseline's scenario id; the server loads the committed pack.
    scenario: str | None = None


# ---------------------------------------------------------------------------
# Live-run state (module-level singleton, one run at a time)
# ---------------------------------------------------------------------------


@dataclass
class _LiveState:
    live_id: str
    arm: str
    seed: int
    running: bool = True
    tick: int = -1
    summary: dict[str, Any] | None = None
    # buffered tick messages for WS replay-on-connect
    buffer: list[dict[str, Any]] = field(default_factory=list)
    # active WebSocket connections
    connections: list[WebSocket] = field(default_factory=list)
    # AAR / memory flags from the start request
    aar: bool = False
    memory: bool = False
    # AAR message stored after generation so late WS connects can replay it
    aar_msg: dict[str, Any] | None = None
    # "ambient" = the auto-looping public demo run; "manual" = an operator run that
    # pre-empts the ambient loop. A manual run blocks a second manual start (409);
    # an ambient run yields to a manual start and resumes when it finishes.
    mode: str = "manual"
    # Set by _run_live / start_live; declared so they're typed and always present
    # (a missing _task previously let stop_live silently orphan a just-started run).
    _society: Any = None
    _task: asyncio.Task[Any] | None = None


_live: _LiveState | None = None
_live_lock = asyncio.Lock()
# Supervisor task for the ambient demo loop (AFTERSHOCK_DEMO_MODE); owned by the app
# lifespan. Kept separate from _live._task (the current run's task).
_ambient_task: asyncio.Task[Any] | None = None


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------


def _resolve_run_dir(run_id: str, runs_root: Path) -> Path | None:
    """Resolve a run_id to its on-disk directory, or None if not found.

    Tries ``runs_root/run_id`` first, then falls back to
    ``runs_root/<_EPISODES_SUBDIR>/run_id`` so the curated society episodes
    nested under ``runs/episodes/`` are reachable by their leaf run_id. The
    fallback candidate is validated to stay within ``runs_root`` (path-traversal
    guard), and ``run_id`` is regex-bound (no slashes), so this cannot escape
    the served root.
    """
    if not _RUN_ID_RE.match(run_id) or run_id in {".", ".."}:
        return None
    resolved_root = runs_root.resolve()
    direct = (runs_root / run_id).resolve()
    try:
        direct.relative_to(resolved_root)
    except ValueError:
        return None
    if direct.is_dir():
        return direct
    # Episodes fallback: runs_root/<_EPISODES_SUBDIR>/run_id
    nested = (runs_root / _EPISODES_SUBDIR / run_id).resolve()
    try:
        nested.relative_to(resolved_root)
    except ValueError:
        return None
    if nested.is_dir():
        return nested
    return None


def _validate_run_id(run_id: str, runs_root: Path) -> Path:
    """Validate run_id and return the resolved run directory.

    Raises HTTPException(404) for any invalid or path-traversal input. Resolves
    nested episode dirs (see ``_resolve_run_dir``) transparently.
    """
    candidate = _resolve_run_dir(run_id, runs_root)
    if candidate is None:
        raise HTTPException(status_code=404, detail="not found")
    return candidate


def _validate_scenario_id(scenario_id: str, scenarios_root: Path) -> Path:
    """Validate a scenario id and return the resolved scenario directory.

    Mirrors ``_validate_run_id``: the id must match ``^[a-z0-9][a-z0-9-]*$`` and the
    resolved candidate must stay within ``scenarios_root`` (defeats ``..``/encoded
    traversal). Raises HTTPException(404) for any invalid or path-traversal input, and
    for a directory without a ``scenario.json``.
    """
    if not _SCENARIO_ID_RE.match(scenario_id) or scenario_id in {".", ".."}:
        raise HTTPException(status_code=404, detail="not found")
    resolved_root = scenarios_root.resolve()
    candidate = (scenarios_root / scenario_id).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="not found") from None
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail="not found")
    if not (candidate / "scenario.json").is_file():
        raise HTTPException(status_code=404, detail="not found")
    return candidate


def _load_pack_or_404(scenario_id: str, scenarios_root: Path) -> ScenarioPack:
    """Validate the id, then load + validate the pack. 404 on any problem."""
    scenario_dir = _validate_scenario_id(scenario_id, scenarios_root)
    try:
        return load_scenario(scenario_dir / "scenario.json")
    except Exception:  # noqa: BLE001  — never leak validation/IO internals
        raise HTTPException(status_code=404, detail="not found") from None


def _caveat_line_for_pack(pack: ScenarioPack) -> str:
    """The honest per-pack caveat line (invariant 4).

    A pack with real first-on-scene baselines (populated ``reference.missions``) is a
    dispatch pack; one without is hazard-timing-only. Chosen so the line never claims a
    category the pack's data does not support.
    """
    if pack.reference.missions:
        return _CAVEAT_DISPATCH
    return _CAVEAT_HAZARD_ONLY


def _scenario_list_entry(pack: ScenarioPack) -> dict[str, Any]:
    """Compact list view for GET /api/scenarios."""
    return {
        "id": pack.id,
        "name": pack.name,
        "hazard": pack.hazard,
        "tick_minutes": pack.tick_minutes,
        "window": pack.window.model_dump(),
        "missions": sum(1 for e in pack.timeline if e.kind == "mission"),
        "sampling": {"kept": pack.sampling.kept, "total": pack.sampling.total},
        "source": [
            {
                "dataset": s.dataset,
                "provider": s.provider,
                "license": s.license,
                "attribution": s.attribution,
            }
            for s in pack.source
        ],
    }


def _scenario_compact(pack: ScenarioPack) -> dict[str, Any]:
    """Compact scenario summary for /api/runs list rows: {id, name, hazard}."""
    return {"id": pack.id, "name": pack.name, "hazard": pack.hazard}


def _scenario_manifest_block(pack: ScenarioPack) -> dict[str, Any]:
    """The run.json scenario block — enough for the UI to render provenance without a
    second fetch (DESIGN.md engine integration)."""
    return {
        "id": pack.id,
        "name": pack.name,
        "hazard": pack.hazard,
        "tick_minutes": pack.tick_minutes,
        "pack_digest": pack.pack_digest,
        "config_sha256": pack.config_sha256,
        "source": [s.model_dump() for s in pack.source],
        "field_provenance": pack.field_provenance.model_dump(),
        "caveat_line": _caveat_line_for_pack(pack),
        "reference_aggregates": dict(pack.reference.aggregates),
    }


def _scenario_compact_from_manifest(manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the compact {id,name,hazard} from a stored run manifest, or None."""
    block = manifest.get("scenario")
    if not isinstance(block, dict):
        return None
    return {
        "id": block.get("id"),
        "name": block.get("name"),
        "hazard": block.get("hazard"),
    }


# ---------------------------------------------------------------------------
# Run scanning helpers
# ---------------------------------------------------------------------------


def _scan_runs(runs_root: Path) -> list[dict[str, Any]]:
    """Scan runs_root for valid run directories, newest first.

    Also descends one level into ``runs_root/<_EPISODES_SUBDIR>/`` so the
    curated society episodes are listed alongside regular runs (their leaf
    run_ids are unique and regex-safe). A run_id collision (same leaf name in
    both roots) keeps the direct-child entry; episode entries are skipped then.
    """
    if not runs_root.exists():
        return []
    results: list[tuple[float, dict[str, Any]]] = []
    seen_ids: set[str] = set()

    scan_dirs: list[Path] = [runs_root]
    episodes_root = runs_root / _EPISODES_SUBDIR
    if episodes_root.is_dir():
        scan_dirs.append(episodes_root)

    for scan_root in scan_dirs:
        for entry in scan_root.iterdir():
            if not entry.is_dir():
                continue
            run_json = entry / "run.json"
            if not run_json.exists():
                continue
            run_id = entry.name
            # Skip an episode whose run_id collides with a direct-child run
            # (the direct child wins; episodes are additive only).
            if scan_root is episodes_root and run_id in seen_ids:
                continue
            try:
                manifest = json.loads(run_json.read_text(encoding="utf-8"))
                ticks_path = entry / "ticks.ndjson"
                ticks_count = 0
                if ticks_path.exists():
                    ticks_count = sum(
                        1
                        for ln in ticks_path.read_text(encoding="utf-8").splitlines()
                        if ln.strip()
                    )
                has_world = (entry / "world.ndjson").exists()
                result: dict[str, Any] = {
                    "run_id": run_id,
                    "seed": manifest.get("seed"),
                    "arm": manifest.get("arm"),
                    "ticks": ticks_count,
                    "final_scores": manifest.get("final_scores", {}),
                    "cost": manifest.get("cost", {}),
                    "has_world": has_world,
                    "scenario": _scenario_compact_from_manifest(manifest),
                    # Branch metadata (only on counterfactual runs); the Compare tab
                    # reads divergeTick from this list row to draw the DIVERGES marker.
                    "counterfactual": manifest.get("counterfactual"),
                }
                mtime = entry.stat().st_mtime
                results.append((mtime, result))
                seen_ids.add(run_id)
            except Exception:  # noqa: BLE001
                continue
    results.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in results]


# ---------------------------------------------------------------------------
# Background live-run task
# ---------------------------------------------------------------------------


async def _broadcast(state: _LiveState, msg: dict[str, Any]) -> None:
    """Send msg to all connected WebSocket clients; remove dead connections."""
    dead: list[WebSocket] = []
    for ws in list(state.connections):
        try:
            await ws.send_json(msg)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        if ws in state.connections:
            state.connections.remove(ws)


async def _run_live(
    state: _LiveState,
    arm: str,
    seed: int,
    ticks: int,
    runs_root: Path,
    do_aar: bool = False,
    do_memory: bool = False,
    pack: ScenarioPack | None = None,
) -> None:
    """Run one live arm in a background task, streaming tick records to the WS clients
    registered on ``state``.

    ``state`` is the _LiveState this run owns; it is passed explicitly (not read from
    the _live global) so that a manual run which pre-empts an ambient one can't make
    the ambient task write into the manual run's state.
    """
    try:
        if arm == "scripted":
            provider = None
        else:
            from aftershock.llm.provider import QwenProvider

            provider = QwenProvider()

        # Load lessons for society arm when memory=True
        lessons: list[str] | None = None
        if do_memory and arm == "society":
            from aftershock.llm.aar import load_lessons

            memory_path = runs_root / "memory.json"
            lessons = load_lessons(memory_path) or None

        setup = build_arm(arm, seed, provider, lessons=lessons, scenario=pack)
    except Exception:  # noqa: BLE001
        async with _live_lock:
            if _live is state:
                state.running = False
        return

    run_id = f"live-{state.live_id[:8]}"
    manifest_rec: dict[str, Any] = {
        "arm": arm,
        "seed": seed,
        "ticks": ticks,
        "run_id": run_id,
        "live_id": state.live_id,
    }
    if pack is not None:
        manifest_rec["scenario"] = _scenario_manifest_block(pack)
    runs_root.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(runs_root, run_id, manifest_rec)

    # Store the society reference so inject_event can reach it
    state._society = setup.society

    def _on_tick(record: Any, world_state_dict: dict[str, Any] | None = None) -> None:
        """Sync tick listener: buffer and push to WS clients."""
        tick_dict = record.model_dump(mode="json")
        msg: dict[str, Any] = {"type": "tick", "record": tick_dict, "world": world_state_dict}
        state.tick = record.tick
        state.buffer.append(msg)
        asyncio.ensure_future(_broadcast(state, msg))

    engine = Engine(
        world=setup.world,
        society=setup.society,
        agents=setup.agents,
        registry=setup.registry,
        roles=setup.roles,
        resolver=setup.resolver,
        recorder=recorder,
        seed=seed,
        max_ticks=ticks,
        agent_timeout_s=setup.default_timeout_s,
        tick_listener=_on_tick,
    )

    try:
        summary_run = await engine.run(inter_tick_delay_s=_LIVE_TICK_DELAY_S)
        summary_dict: dict[str, Any] = {
            "run_id": summary_run.run_id,
            "seed": summary_run.seed,
            "ticks_run": summary_run.ticks_run,
            "final_scores": summary_run.final_scores,
            "cost": summary_run.cost,
            "run_dir": summary_run.run_dir,
            "arm": arm,
        }
        state.summary = summary_dict
        done_msg: dict[str, Any] = {"type": "done", "summary": summary_dict}
        await _broadcast(state, done_msg)

        # AAR generation: only when requested and a provider is available
        if do_aar and provider is not None:
            run_dir_path = recorder.run_dir
            aar_msg: dict[str, Any]
            try:
                from aftershock.llm.aar import append_lessons, generate_aar

                report = await generate_aar(run_dir_path, provider)
                aar_msg = {"type": "aar", "report": report}
                # Append lessons to memory.json
                lessons_from_run: list[str] = report.get("lessons", [])
                if lessons_from_run:
                    memory_path = runs_root / "memory.json"
                    append_lessons(memory_path, run_id, lessons_from_run)
            except Exception as aar_exc:  # noqa: BLE001
                logger.warning("AAR generation failed", exc_info=aar_exc)
                aar_msg = {"type": "aar", "error": str(aar_exc)}
            state.aar_msg = aar_msg
            await _broadcast(state, aar_msg)

    except Exception as exc:  # noqa: BLE001
        logger.error("live run failed", exc_info=exc)
        with contextlib.suppress(Exception):
            await _broadcast(state, {"type": "error", "detail": "live run encountered an error"})
    finally:
        # Close the recorder even on cancel/error — engine.run() only closes it on
        # its happy path, so a Stop mid-run would otherwise leak file handles
        # (the Stop button is built for repeated use within a demo session).
        with contextlib.suppress(Exception):
            recorder.close()
        state.running = False
        for ws in list(state.connections):
            with contextlib.suppress(Exception):
                await ws.close()
        state.connections.clear()


def _cf_run_id(live_id: str, req: CounterfactualRequest) -> str:
    """Deterministic branch run id, shared by the endpoint (returned to the client)
    and the background runner so Compare can select the branch once it appears.

    Must match _RUN_ID_RE (^[A-Za-z0-9._-]+$) so the run is loadable via
    /api/runs/{id} — hence "-at{N}" rather than "@{N}"."""
    tag = req.kind if req.kind == "none" else f"{req.kind}-at{req.at_tick}"
    return f"cf-{live_id[:8]}-{tag}"


async def _run_counterfactual_live(
    state: _LiveState,
    req: CounterfactualRequest,
    runs_root: Path,
    run_id: str,
    scenario_pack: ScenarioPack | None = None,
) -> None:
    """Run one counterfactual branch in a background task, streaming to the WS clients
    on ``state`` exactly like _run_live. The branch lands in runs/ under a distinct
    run_id and is replayable by Compare against its baseline.
    """
    from aftershock.town.counterfactual import Intervention, run_counterfactual

    def _on_tick(record: Any, world_state_dict: dict[str, Any] | None = None) -> None:
        tick_dict = record.model_dump(mode="json")
        msg: dict[str, Any] = {"type": "tick", "record": tick_dict, "world": world_state_dict}
        state.tick = record.tick
        state.buffer.append(msg)
        asyncio.ensure_future(_broadcast(state, msg))

    try:
        provider = None
        if req.arm != "scripted":
            from aftershock.llm.provider import QwenProvider

            provider = QwenProvider()

        intervention = Intervention(
            at_tick=req.at_tick, kind=req.kind, target=req.target, params=dict(req.params)
        )
        # When branching a scenario baseline, record its provenance block so the branch
        # is honestly labelled REAL (and its world — same pack + seed — yields a truly
        # byte-identical prefix to the scenario baseline).
        extra_manifest = (
            {"scenario": _scenario_manifest_block(scenario_pack)} if scenario_pack else None
        )

        summary_run = await run_counterfactual(
            arm=req.arm,
            seed=req.seed,
            ticks=req.ticks,
            intervention=intervention,
            runs_root=runs_root,
            run_id=run_id,
            provider=provider,
            scenario=scenario_pack,
            baseline_run_id=req.baseline_run_id,
            tick_listener=_on_tick,
            # No inter-tick pacing: Compare REPLAYS the completed branch via its
            # playback clock (it doesn't watch the live WS stream), so pacing the
            # run here would only delay when the branch becomes replayable.
            extra_manifest=extra_manifest,
        )
        summary_dict: dict[str, Any] = {
            "run_id": summary_run.run_id,
            "seed": summary_run.seed,
            "ticks_run": summary_run.ticks_run,
            "final_scores": summary_run.final_scores,
            "cost": summary_run.cost,
            "run_dir": summary_run.run_dir,
            "arm": req.arm,
        }
        state.summary = summary_dict
        await _broadcast(state, {"type": "done", "summary": summary_dict})
    except Exception as exc:  # noqa: BLE001
        logger.error("counterfactual run failed", exc_info=exc)
        with contextlib.suppress(Exception):
            await _broadcast(
                state, {"type": "error", "detail": "counterfactual run encountered an error"}
            )
    finally:
        state.running = False
        for ws in list(state.connections):
            with contextlib.suppress(Exception):
                await ws.close()
        state.connections.clear()


async def _ambient_demo_loop(runs_root: Path) -> None:
    """Keep the public Live tab alive: run back-to-back scripted demo runs whenever no
    manual (operator) run holds the floor. A manual start pre-empts the current ambient
    run (cancelling its task); this loop resumes once that manual run finishes.

    Server-driven so the demo needs no client mutation — the browser only watches the
    ungated WS. Enabled by AFTERSHOCK_DEMO_MODE; owned and cancelled by the app lifespan.
    """
    global _live
    seed_idx = 0
    fail_streak = 0
    while True:
        current: asyncio.Task[Any] | None = None
        state_ref: _LiveState | None = None
        async with _live_lock:
            if _live is None or not _live.running:
                seed = _AMBIENT_SEEDS[seed_idx % len(_AMBIENT_SEEDS)]
                seed_idx += 1
                _live = _LiveState(
                    live_id=str(uuid.uuid4()),
                    arm="scripted",
                    seed=seed,
                    mode="ambient",
                )
                _live._task = asyncio.create_task(
                    _run_live(_live, "scripted", seed, _AMBIENT_TICKS, runs_root)
                )
                current = _live._task
                state_ref = _live
        if current is not None:
            # Wait for this ambient run to finish or be pre-empted by a manual start.
            try:
                await current
            except asyncio.CancelledError:
                # asyncio propagates an outer-task cancel down to the awaited inner task,
                # so `current` is cancelled in BOTH cases. Distinguish via THIS task's
                # own cancellation state: if the loop itself is being cancelled (lifespan
                # shutdown), propagate and exit; otherwise the ambient run was pre-empted
                # by a manual start, so keep looping.
                self_task = asyncio.current_task()
                if self_task is not None and self_task.cancelling() > 0:
                    raise
            except Exception:  # noqa: BLE001 — an ambient run error just rolls to the next
                pass
            # A run that never emitted a tick failed to set up (e.g. an unwritable runs
            # dir). Back off exponentially on a persistent failure so the loop can't
            # busy-spin or flood the logs; a successful run resets the streak.
            if state_ref is not None and state_ref.tick < 0:
                fail_streak += 1
            else:
                fail_streak = 0
            delay = _AMBIENT_RESTART_DELAY_S
            if fail_streak >= 3:
                delay = min(60.0, _AMBIENT_RESTART_DELAY_S * 2 ** (fail_streak - 2))
            await asyncio.sleep(delay)
        else:
            # A manual run holds the floor; re-check shortly.
            await asyncio.sleep(_AMBIENT_POLL_S)


# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------


def create_app(
    runs_root: Path,
    bench_root: Path | None = None,
    host: str = "127.0.0.1",
    scenarios_root: Path | None = None,
) -> FastAPI:
    """Create and return the FastAPI application.

    Args:
        runs_root:      Directory where run directories are stored.
        bench_root:     Directory where benchmark results.json files live.
                        Defaults to bench/results/ relative to cwd.
        host:           The bind host (passed from CLI). Used for startup safety check.
        scenarios_root: Directory holding committed scenario packs
                        (``<id>/scenario.json``). Defaults to scenarios/ relative to cwd.
    """
    if bench_root is None:
        bench_root = Path("bench") / "results"
    if scenarios_root is None:
        scenarios_root = Path("scenarios")

    # ------------------------------------------------------------------
    # Auth token + CORS setup
    # ------------------------------------------------------------------
    _app_token: str | None = os.environ.get("OBSERVATORY_TOKEN") or None
    _allow_origin: str = os.environ.get("OBSERVATORY_ORIGIN", "http://127.0.0.1:8788")

    # Safety check: warn loudly when binding to a public interface without a token
    if host not in ("127.0.0.1", "localhost", "::1") and not _app_token:
        logger.warning(
            "SECURITY WARNING: aftershock serve is bound to %s with no "
            "OBSERVATORY_TOKEN set. Mutating endpoints are open to the internet. "
            "Set OBSERVATORY_TOKEN=<secret> to require authentication.",
            host,
        )

    def _require_token(x_observatory_token: str | None = Header(default=None)) -> None:
        if not _app_token:
            return  # token protection not configured — skip (loopback-only deployments)
        if not x_observatory_token or not secrets.compare_digest(x_observatory_token, _app_token):
            raise HTTPException(status_code=401, detail="unauthorized")

    @contextlib.asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # When AFTERSHOCK_DEMO_MODE is set (the public judge box), run the ambient demo
        # loop for the lifetime of the app so the Live tab is alive over the read-only WS
        # with no client mutation. Cancelled cleanly on shutdown.
        global _ambient_task
        if os.environ.get("AFTERSHOCK_DEMO_MODE"):
            _ambient_task = asyncio.create_task(_ambient_demo_loop(runs_root))
        try:
            yield
        finally:
            loop_task = _ambient_task
            _ambient_task = None
            if loop_task is not None:
                loop_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await loop_task
            # Stop any in-flight run too, so shutdown leaves no dangling task.
            state = _live
            if state is not None and state.running:
                state.running = False
                run_task = state._task
                if run_task is not None and not run_task.done():
                    run_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await run_task

    app = FastAPI(title="Aftershock Observatory", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_allow_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["x-observatory-token", "content-type"],
        allow_credentials=False,
    )

    # ------------------------------------------------------------------
    # GET /api/status
    # ------------------------------------------------------------------
    # Voucher/key detection for graceful UI degradation. Reports whether the
    # DashScope key is configured so the frontend can show a "Qwen society
    # live-engine offline (voucher pending)" chip instead of a raw 503 when an
    # operator picks a solo/swarm/society live or counterfactual run. Scripted
    # arms are keyless and never gated. Does NOT leak the key itself.

    @app.get("/api/status")
    async def status() -> JSONResponse:
        return JSONResponse(
            {
                "llm_key": bool(os.environ.get("DASHSCOPE_API_KEY")),
                "demo_mode": bool(os.environ.get("AFTERSHOCK_DEMO_MODE")),
                "llm_arms": list(_LLM_ARMS),
            }
        )

    # ------------------------------------------------------------------
    # GET /api/determinism
    # ------------------------------------------------------------------
    # Re-runs the SCRIPTED engine twice (seed 42, 60 ticks — the canonical
    # `aftershock verify` command) and compares world_digest sequences. Cached
    # per-process after the first call so the BenchTab badge is instant. The
    # claim is scoped to the scripted arm ONLY — DashScope ignores `seed`, so
    # LLM/society arms are irreducibly stochastic and never implied reproducible.

    async def _run_determinism_check() -> dict[str, Any]:
        import tempfile

        from aftershock.kernel.engine import Engine as _Engine
        from aftershock.kernel.recorder import Recorder as _Recorder
        from aftershock.town.arms import build_arm as _build_arm

        async def _run_into(tmp: Path, tag: str) -> list[str]:
            run_id = f"verify-{tag}"
            setup = _build_arm("scripted", _DETERMINISM_SEED, None)
            manifest = {
                "run_id": run_id,
                "seed": _DETERMINISM_SEED,
                "ticks": _DETERMINISM_TICKS,
                "arm": "scripted",
            }
            recorder = _Recorder(tmp, run_id, manifest)
            engine = _Engine(
                world=setup.world,
                society=setup.society,
                agents=setup.agents,
                registry=setup.registry,
                roles=setup.roles,
                resolver=setup.resolver,
                recorder=recorder,
                seed=_DETERMINISM_SEED,
                max_ticks=_DETERMINISM_TICKS,
                agent_timeout_s=setup.default_timeout_s,
            )
            await engine.run()
            _, records, _worlds = load_run(tmp / run_id)
            return [r.world_digest for r in records]

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            a = await _run_into(tmp / "a", "a")
            b = await _run_into(tmp / "b", "b")
        # Guard against an empty digest list returning a vacuous pass —
        # defense-in-depth (not reachable today: the scripted engine always
        # emits >=1 tick, but a future early-exit path could change that).
        passed = bool(a) and a == b
        return {
            "arm": "scripted",
            "seed": _DETERMINISM_SEED,
            "ticks": _DETERMINISM_TICKS,
            "passed": passed,
            "n_digests": len(a),
            # Explicit honesty boundary: only the scripted arm is verified.
            "scope": "scripted engine only",
            "note": (
                "Two seeded scripted runs produce identical world-digest "
                "sequences. DashScope ignores `seed`, so LLM/society arms are "
                "NOT reproducible."
            ),
        }

    @app.get("/api/determinism")
    async def determinism() -> JSONResponse:
        global _determinism_cache, _determinism_lock
        if _determinism_cache is not None:
            return JSONResponse(_determinism_cache)
        if _determinism_lock is None:
            _determinism_lock = asyncio.Lock()
        async with _determinism_lock:
            # Re-check inside the lock — a racing caller may have populated it.
            if _determinism_cache is not None:
                return JSONResponse(_determinism_cache)
            _determinism_cache = await _run_determinism_check()
        return JSONResponse(_determinism_cache)

    # ------------------------------------------------------------------
    # GET /api/runs
    # ------------------------------------------------------------------

    @app.get("/api/runs")
    async def list_runs() -> JSONResponse:
        runs = _scan_runs(runs_root)
        return JSONResponse(runs)

    # ------------------------------------------------------------------
    # GET /api/runs/{run_id}
    # ------------------------------------------------------------------

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str) -> JSONResponse:
        run_dir = _validate_run_id(run_id, runs_root)
        try:
            manifest, ticks, worlds = load_run(run_dir)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="not found") from None
        scenario_block = manifest.get("scenario")
        return JSONResponse({
            "run_id": run_id,
            "manifest": manifest,
            "final_scores": manifest.get("final_scores", {}),
            "n_ticks": len(ticks),
            "has_world": worlds is not None,
            "scenario": scenario_block if isinstance(scenario_block, dict) else None,
        })

    # ------------------------------------------------------------------
    # GET /api/runs/{run_id}/conformance
    # ------------------------------------------------------------------

    @app.get("/api/runs/{run_id}/conformance")
    async def run_conformance(run_id: str) -> JSONResponse:
        _CONF_MAX_BYTES = 1024 * 1024  # 1 MB cap

        run_dir = _validate_run_id(run_id, runs_root)
        conf_path = run_dir / "conformance.json"
        if not conf_path.exists():
            raise HTTPException(status_code=404, detail="conformance not found")
        try:
            raw_bytes = conf_path.read_bytes()
            if len(raw_bytes) > _CONF_MAX_BYTES:
                raise ValueError("conformance.json exceeds size cap")
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="conformance not found") from None
        return JSONResponse(data)

    # ------------------------------------------------------------------
    # GET /api/runs/{run_id}/aar
    # ------------------------------------------------------------------

    @app.get("/api/runs/{run_id}/aar")
    async def run_aar(run_id: str) -> JSONResponse:
        from aftershock.llm.aar import AAR_SCHEMA

        _AAR_MAX_BYTES = 512 * 1024  # 512 KB cap to prevent DoS amplification

        run_dir = _validate_run_id(run_id, runs_root)
        aar_path = run_dir / "aar.json"
        if not aar_path.exists():
            raise HTTPException(status_code=404, detail="aar not found")
        try:
            raw_bytes = aar_path.read_bytes()
            if len(raw_bytes) > _AAR_MAX_BYTES:
                raise ValueError("aar.json exceeds size cap")
            data = json.loads(raw_bytes.decode("utf-8"))
            report = AAR_SCHEMA.model_validate(data)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="aar not found") from None
        return JSONResponse(report.model_dump())

    # ------------------------------------------------------------------
    # GET /api/runs/{run_id}/ticks
    # ------------------------------------------------------------------

    @app.get("/api/runs/{run_id}/ticks")
    async def run_ticks(
        run_id: str,
        start: int = 0,
        limit: int = 50,
    ) -> JSONResponse:
        run_dir = _validate_run_id(run_id, runs_root)
        limit = min(limit, _MAX_LIMIT)
        if limit < 1:
            limit = 1
        if start < 0:
            start = 0
        try:
            _manifest, ticks, worlds = load_run(run_dir)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=404, detail="not found") from None

        total = len(ticks)
        page = ticks[start : start + limit]
        page_dicts = [t.model_dump(mode="json") for t in page]

        worlds_page: list[dict[str, Any]] | None = None
        if worlds is not None:
            # Each world entry is stored as {tick, state} — unwrap to flat WorldState
            raw_worlds = worlds[start : start + limit]
            worlds_page = [
                w["state"] if isinstance(w, dict) and "state" in w else w
                for w in raw_worlds
            ]

        return JSONResponse({
            "ticks": page_dicts,
            "worlds": worlds_page,
            "total": total,
        })

    # ------------------------------------------------------------------
    # GET /api/bench
    # ------------------------------------------------------------------

    @app.get("/api/bench")
    async def bench_results() -> JSONResponse:
        if not bench_root.exists():
            return JSONResponse([])
        results: list[tuple[float, str, Any]] = []
        # results.json files live in dated subdirectories (bench/results/<date>/),
        # or directly under bench_root — scan recursively for the canonical name.
        for entry in sorted(bench_root.rglob("results.json")):
            try:
                data = json.loads(entry.read_text(encoding="utf-8"))
                mtime = entry.stat().st_mtime
                results.append((mtime, entry.parent.name, data))
            except Exception:  # noqa: BLE001
                continue
        # Canonical demo batch first, then the rest newest-first by mtime.
        results.sort(key=lambda x: (x[1] != _CANONICAL_BENCH_DIR, -x[0]))
        # Attach a pure paired-stats block (bootstrap CI + sign-test p + power +
        # verdict) to each result, computed server-side from its `paired` table
        # so the BenchTab never reimplements stats in TS. Control = the
        # deterministic scripted baseline; an arm with no common seeds is omitted
        # (never an error), so a single-arm result yields an empty list.
        from aftershock.bench import paired_comparisons

        served: list[dict[str, Any]] = []
        for _, dirname, data in results:
            if isinstance(data, dict):
                data = dict(data)
                data["batch"] = dirname
                data["canonical"] = dirname == _CANONICAL_BENCH_DIR
                if isinstance(data.get("paired"), dict):
                    prov = data.get("provenance")
                    data["paired_stats"] = paired_comparisons(
                        data["paired"],
                        provenance=prov if isinstance(prov, dict) else None,
                    )
            served.append(data)
        return JSONResponse(served)

    # ------------------------------------------------------------------
    # GET /api/scenarios  (ungated, like every other GET)
    # ------------------------------------------------------------------

    @app.get("/api/scenarios")
    async def list_scenarios() -> JSONResponse:
        if not scenarios_root.exists() or not scenarios_root.is_dir():
            return JSONResponse([])
        entries: list[dict[str, Any]] = []
        for entry in sorted(scenarios_root.iterdir()):
            if not entry.is_dir():
                continue
            scenario_id = entry.name
            # Apply the same id grammar as the detail endpoint; skip non-conforming dirs.
            if not _SCENARIO_ID_RE.match(scenario_id):
                continue
            scenario_json = entry / "scenario.json"
            if not scenario_json.is_file():
                continue
            try:
                pack = load_scenario(scenario_json)
            except Exception:  # noqa: BLE001 — skip malformed packs, never 500
                continue
            entries.append(_scenario_list_entry(pack))
        return JSONResponse(entries)

    # ------------------------------------------------------------------
    # GET /api/scenarios/{scenario_id}  (full pack incl. reference, ungated)
    # ------------------------------------------------------------------

    @app.get("/api/scenarios/{scenario_id}")
    async def scenario_detail(scenario_id: str) -> JSONResponse:
        pack = _load_pack_or_404(scenario_id, scenarios_root)
        return JSONResponse(pack.model_dump())

    # ------------------------------------------------------------------
    # GET /api/live
    # ------------------------------------------------------------------

    @app.get("/api/live")
    async def live_status() -> JSONResponse:
        global _live
        if _live is None:
            return JSONResponse({
                "running": False,
                "live_id": None,
                "tick": -1,
                "arm": None,
                "seed": None,
                "mode": None,
            })
        return JSONResponse({
            "running": _live.running,
            "live_id": _live.live_id,
            "tick": _live.tick,
            "arm": _live.arm,
            "seed": _live.seed,
            "mode": _live.mode,
        })

    # ------------------------------------------------------------------
    # POST /api/live
    # ------------------------------------------------------------------

    @app.post("/api/live", dependencies=[Depends(_require_token)])
    async def start_live(req: LiveRunRequest) -> JSONResponse:
        global _live

        # Resolve the scenario pack (unknown/invalid id -> 404) before computing ticks:
        # the omitted-ticks default depends on the pack's timeline.
        pack: ScenarioPack | None = None
        if req.scenario is not None:
            pack = _load_pack_or_404(req.scenario, scenarios_root)

        # Effective ticks: omitted ("None") -> server default
        #   synthetic: 30; scenario: min(last timeline tick + 20, 120) via the
        #   shared scenario_tick_budget helper (same logic the CLI uses).
        # An explicit value is honored (capped above and floored below for scenarios).
        if req.ticks is None:
            ticks = scenario_tick_budget(pack) if pack is not None else _DEFAULT_SYNTHETIC_TICKS
        else:
            ticks = req.ticks

        # For a scenario run, an explicit under-budget ticks value would silently
        # truncate the real timeline — refuse it (mirrors the CLI's hard error).
        if pack is not None and req.ticks is not None:
            budget = scenario_tick_budget(pack)
            if req.ticks < budget:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"ticks {req.ticks} is under the scenario budget ({budget}); "
                        f"omit ticks or pass >= {budget}"
                    ),
                )

        # ticks cap (applies to explicit values; the scenario default is pre-capped)
        if ticks > _MAX_TICKS_LIVE:
            raise HTTPException(
                status_code=422, detail=f"ticks must be <= {_MAX_TICKS_LIVE}"
            )

        # LLM arms need API key
        if req.arm in _LLM_ARMS and not os.environ.get("DASHSCOPE_API_KEY"):
            raise HTTPException(
                status_code=503,
                detail="DASHSCOPE_API_KEY is not set; set it to run LLM arms",
            )

        live_id = str(uuid.uuid4())

        async with _live_lock:
            # One manual run at a time: this 409 check and the assignment below sit in a
            # SINGLE lock block (no await between them) so two concurrent manual starts
            # can't both pass. An in-flight AMBIENT demo run is pre-empted instead so the
            # operator takes the floor; the ambient loop resumes once this run ends. We
            # cancel the ambient task AFTER reassigning _live, outside the lock.
            if _live is not None and _live.running and _live.mode == "manual":
                raise HTTPException(
                    status_code=409, detail="a live run is already in progress"
                )
            preempt = (
                _live._task
                if (_live is not None and _live.running and _live.mode == "ambient")
                else None
            )
            _live = _LiveState(
                live_id=live_id,
                arm=req.arm,
                seed=req.seed,
                aar=req.aar,
                memory=req.memory,
                mode="manual",
            )
            # Create the task and retain a strong ref to it BEFORE releasing the lock.
            # create_task only schedules — the coroutine body doesn't run until the next
            # loop turn — so a racing stop_live always observes a set _task, and the
            # state is passed explicitly into _run_live (no _live-global capture race).
            _live._task = asyncio.create_task(
                _run_live(
                    _live,
                    req.arm,
                    req.seed,
                    ticks,
                    runs_root,
                    do_aar=req.aar,
                    do_memory=req.memory,
                    pack=pack,
                )
            )
        if preempt is not None and not preempt.done():
            preempt.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await preempt

        return JSONResponse({"live_id": live_id})

    # ------------------------------------------------------------------
    # POST /api/live/inject
    # ------------------------------------------------------------------

    @app.post("/api/live/inject", dependencies=[Depends(_require_token)])
    async def inject_event(req: InjectRequest) -> JSONResponse:
        if req.kind not in _VALID_INJECT_KINDS:
            raise HTTPException(
                status_code=422,
                detail=f"invalid kind {req.kind!r}; valid: {sorted(_VALID_INJECT_KINDS)}",
            )
        global _live
        if _live is None or not _live.running:
            raise HTTPException(status_code=404, detail="no live run in progress")
        soc = getattr(_live, "_society", None)
        if soc is None:
            raise HTTPException(status_code=404, detail="no live run in progress")
        # Cap the injection queue to prevent unbounded-memory DoS
        if len(getattr(soc, "_injection_queue", [])) >= _MAX_PENDING_INJECTIONS:
            raise HTTPException(status_code=429, detail="injection queue full; slow down")
        try:
            soc.inject_event(req.kind, req.district)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return JSONResponse({"ok": True})

    @app.post("/api/live/stop", dependencies=[Depends(_require_token)])
    async def stop_live() -> JSONResponse:
        """Cancel the in-progress live run so an operator can take manual control
        (e.g. interrupt the auto-started scripted demo to launch a real-agent run).
        Idempotent: a no-op 200 when nothing is running."""
        global _live
        async with _live_lock:
            state = _live
            if state is None or not state.running:
                return JSONResponse({"ok": True, "running": False})
            # Flag stopped first so a racing inject/start sees the run as over.
            state.running = False
            task = state._task
        if task is not None and not task.done():
            task.cancel()
            # Awaiting the cancelled task lets _run_live's finally close the WS
            # clients and the recorder before we return.
            with contextlib.suppress(asyncio.CancelledError):
                await task
        return JSONResponse({"ok": True, "running": False})

    # ------------------------------------------------------------------
    # POST /api/counterfactual
    # ------------------------------------------------------------------

    @app.post("/api/counterfactual", dependencies=[Depends(_require_token)])
    async def start_counterfactual(req: CounterfactualRequest) -> JSONResponse:
        """Branch a run: re-run the seed with one intervention at tick N, streaming
        the branch over the same /ws/live channel as a live run. The client then
        flips Compare to (baseline_run_id, branch_run_id)."""
        from aftershock.town.counterfactual import INTERVENTION_KINDS

        global _live

        if req.at_tick < 0 or req.at_tick >= req.ticks:
            raise HTTPException(
                status_code=422,
                detail=f"at_tick must be in [0, {req.ticks}) (got {req.at_tick})",
            )
        if req.ticks > _MAX_TICKS_LIVE:
            raise HTTPException(status_code=422, detail=f"ticks must be <= {_MAX_TICKS_LIVE}")

        # Validate the intervention synchronously (422) so the operator gets immediate
        # feedback rather than a vague async WS error. (A bad inject district is world-
        # dependent and is caught eagerly inside run_counterfactual, surfacing loudly.)
        if req.kind not in INTERVENTION_KINDS:
            raise HTTPException(
                status_code=422,
                detail=f"invalid kind {req.kind!r}; valid: {sorted(INTERVENTION_KINDS)}",
            )
        if req.kind == "inject_event":
            event = str(req.params.get("event", "fire"))
            if event not in _VALID_INJECT_KINDS:
                raise HTTPException(
                    status_code=422,
                    detail=f"invalid inject event {event!r}; valid: {sorted(_VALID_INJECT_KINDS)}",
                )
            if not req.target:
                raise HTTPException(
                    status_code=422, detail="inject_event requires a target district"
                )
        if req.kind == "kill_agent" and not req.target:
            raise HTTPException(status_code=422, detail="kill_agent requires a target agent id")

        if req.arm in _LLM_ARMS and not os.environ.get("DASHSCOPE_API_KEY"):
            raise HTTPException(
                status_code=503,
                detail="DASHSCOPE_API_KEY is not set; set it to run LLM arms",
            )

        # Scenario baseline: load the committed pack (404 on a bad id) so the branch
        # rebuilds the SAME world and the byte-identical-prefix claim actually holds.
        scenario_pack: ScenarioPack | None = None
        if req.scenario:
            scenario_pack = _load_pack_or_404(req.scenario, scenarios_root)

        live_id = str(uuid.uuid4())
        run_id = _cf_run_id(live_id, req)
        async with _live_lock:
            if _live is not None and _live.running and _live.mode == "manual":
                raise HTTPException(
                    status_code=409, detail="a live run is already in progress"
                )
            preempt = (
                _live._task
                if (_live is not None and _live.running and _live.mode == "ambient")
                else None
            )
            _live = _LiveState(live_id=live_id, arm=req.arm, seed=req.seed, mode="manual")
            _live._task = asyncio.create_task(
                _run_counterfactual_live(_live, req, runs_root, run_id, scenario_pack)
            )
        if preempt is not None and not preempt.done():
            preempt.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await preempt
        return JSONResponse({"live_id": live_id, "run_id": run_id})

    # ------------------------------------------------------------------
    # WS /ws/live
    # ------------------------------------------------------------------

    @app.websocket("/ws/live")
    async def ws_live(websocket: WebSocket) -> None:
        await websocket.accept()
        global _live
        state = _live

        if state is not None:
            # If already done before we even start, replay buffer + done + aar then close
            if not state.running:
                snapshot = list(state.buffer)
                for msg in snapshot:
                    try:
                        await websocket.send_json(msg)
                    except Exception:  # noqa: BLE001
                        await websocket.close()
                        return
                if state.summary is not None:
                    with contextlib.suppress(Exception):
                        await websocket.send_json({"type": "done", "summary": state.summary})
                if state.aar_msg is not None:
                    with contextlib.suppress(Exception):
                        await websocket.send_json(state.aar_msg)
                await websocket.close()
                return

            # Register BEFORE replaying the buffer so no tick fired during replay is lost.
            # We capture buffer length first; _broadcast covers anything appended after.
            state.connections.append(websocket)
            snapshot_len = len(state.buffer)
            for msg in state.buffer[:snapshot_len]:
                try:
                    await websocket.send_json(msg)
                except Exception:  # noqa: BLE001
                    if websocket in state.connections:
                        state.connections.remove(websocket)
                    await websocket.close()
                    return

        try:
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                except TimeoutError:
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:  # noqa: BLE001
                        break
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            if state is not None and websocket in state.connections:
                state.connections.remove(websocket)

    # ------------------------------------------------------------------
    # Static files
    # ------------------------------------------------------------------

    web_dist = Path(__file__).parent.parent.parent / "web" / "dist"
    if web_dist.exists() and web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="static")
    else:

        @app.get("/")
        async def root() -> JSONResponse:
            return JSONResponse({"hint": "run npm install && npm run build in web/"})

    return app
