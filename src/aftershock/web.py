"""FastAPI web server for the Aftershock observatory.

Provides:
  - Run listing / detail / paged ticks (replays with world states)
  - Benchmark results (/api/bench)
  - Live run lifecycle: POST /api/live, WS /ws/live, POST /api/live/inject
  - Static serving of web/dist when present

Security:
  - run_id validated against ^[A-Za-z0-9._-]+$ and resolved().is_relative_to(runs_root)
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MAX_TICKS_LIVE = 120
_MAX_LIMIT = 200
_VALID_INJECT_KINDS = frozenset({"fire", "aftershock", "road_block"})
_MAX_PENDING_INJECTIONS = 50


# ---------------------------------------------------------------------------
# Request/response models (module-level so FastAPI resolves them correctly)
# ---------------------------------------------------------------------------


class LiveRunRequest(BaseModel):
    arm: str
    seed: int
    ticks: int = 30
    aar: bool = False
    memory: bool = False


class InjectRequest(BaseModel):
    kind: str
    district: str


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


_live: _LiveState | None = None
_live_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------


def _validate_run_id(run_id: str, runs_root: Path) -> Path:
    """Validate run_id and return the resolved run directory.

    Raises HTTPException(404) for any invalid or path-traversal input.
    """
    if not _RUN_ID_RE.match(run_id) or run_id in {".", ".."}:
        raise HTTPException(status_code=404, detail="not found")
    resolved_root = runs_root.resolve()
    candidate = (runs_root / run_id).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="not found") from None
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=404, detail="not found")
    return candidate


# ---------------------------------------------------------------------------
# Run scanning helpers
# ---------------------------------------------------------------------------


def _scan_runs(runs_root: Path) -> list[dict[str, Any]]:
    """Scan runs_root for valid run directories, newest first."""
    if not runs_root.exists():
        return []
    results: list[tuple[float, dict[str, Any]]] = []
    for entry in runs_root.iterdir():
        if not entry.is_dir():
            continue
        run_json = entry / "run.json"
        if not run_json.exists():
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
                "run_id": entry.name,
                "seed": manifest.get("seed"),
                "arm": manifest.get("arm"),
                "ticks": ticks_count,
                "final_scores": manifest.get("final_scores", {}),
                "cost": manifest.get("cost", {}),
                "has_world": has_world,
            }
            mtime = entry.stat().st_mtime
            results.append((mtime, result))
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
    arm: str,
    seed: int,
    ticks: int,
    runs_root: Path,
    do_aar: bool = False,
    do_memory: bool = False,
) -> None:
    """Run one live arm in a background task, streaming tick records to WS clients."""
    global _live
    state = _live
    if state is None:
        return

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

        setup = build_arm(arm, seed, provider, lessons=lessons)
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
    runs_root.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(runs_root, run_id, manifest_rec)

    # Store the society reference so inject_event can reach it
    state._society = setup.society  # type: ignore[attr-defined]

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
        summary_run = await engine.run()
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
        state.running = False
        for ws in list(state.connections):
            with contextlib.suppress(Exception):
                await ws.close()
        state.connections.clear()


# ---------------------------------------------------------------------------
# create_app
# ---------------------------------------------------------------------------


def create_app(
    runs_root: Path,
    bench_root: Path | None = None,
    host: str = "127.0.0.1",
) -> FastAPI:
    """Create and return the FastAPI application.

    Args:
        runs_root:  Directory where run directories are stored.
        bench_root: Directory where benchmark results.json files live.
                    Defaults to bench/results/ relative to cwd.
        host:       The bind host (passed from CLI). Used for startup safety check.
    """
    if bench_root is None:
        bench_root = Path("bench") / "results"

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

    app = FastAPI(title="Aftershock Observatory")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_allow_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["x-observatory-token", "content-type"],
        allow_credentials=False,
    )

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
        return JSONResponse({
            "run_id": run_id,
            "manifest": manifest,
            "final_scores": manifest.get("final_scores", {}),
            "n_ticks": len(ticks),
            "has_world": worlds is not None,
        })

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
        results: list[tuple[float, Any]] = []
        # results.json files live in dated subdirectories (bench/results/<date>/),
        # or directly under bench_root — scan recursively for the canonical name.
        for entry in sorted(bench_root.rglob("results.json")):
            try:
                data = json.loads(entry.read_text(encoding="utf-8"))
                mtime = entry.stat().st_mtime
                results.append((mtime, data))
            except Exception:  # noqa: BLE001
                continue
        results.sort(key=lambda x: x[0], reverse=True)
        return JSONResponse([r for _, r in results])

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
            })
        return JSONResponse({
            "running": _live.running,
            "live_id": _live.live_id,
            "tick": _live.tick,
            "arm": _live.arm,
            "seed": _live.seed,
        })

    # ------------------------------------------------------------------
    # POST /api/live
    # ------------------------------------------------------------------

    @app.post("/api/live", dependencies=[Depends(_require_token)])
    async def start_live(req: LiveRunRequest) -> JSONResponse:
        global _live

        # One at a time
        async with _live_lock:
            if _live is not None and _live.running:
                raise HTTPException(
                    status_code=409, detail="a live run is already in progress"
                )

        # ticks cap
        if req.ticks > _MAX_TICKS_LIVE:
            raise HTTPException(
                status_code=422, detail=f"ticks must be <= {_MAX_TICKS_LIVE}"
            )

        # LLM arms need API key
        llm_arms = ("solo", "swarm", "society")
        if req.arm in llm_arms and not os.environ.get("DASHSCOPE_API_KEY"):
            raise HTTPException(
                status_code=503,
                detail="DASHSCOPE_API_KEY is not set; set it to run LLM arms",
            )

        live_id = str(uuid.uuid4())

        async with _live_lock:
            _live = _LiveState(
                live_id=live_id,
                arm=req.arm,
                seed=req.seed,
                aar=req.aar,
                memory=req.memory,
            )

        task = asyncio.create_task(
            _run_live(
                req.arm,
                req.seed,
                req.ticks,
                runs_root,
                do_aar=req.aar,
                do_memory=req.memory,
            )
        )
        _live._task = task  # type: ignore[attr-defined]  # retain strong ref to prevent GC

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
