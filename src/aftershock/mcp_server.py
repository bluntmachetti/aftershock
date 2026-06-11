"""MCP spectator for Aftershock runs.

Exposes a FastMCP server (stdio transport, name "aftershock") that lets an LLM
client browse recorded runs and inject live events into a running server.

Run via: aftershock mcp [--runs-dir runs]
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from aftershock.kernel.recorder import load_run

# ---------------------------------------------------------------------------
# Server instance (module-level so CLI can call mcp.run())
# ---------------------------------------------------------------------------

mcp = FastMCP("aftershock")

# Injected at startup by create_server() or the CLI entry point.
_runs_root: Path = Path("runs")
_bench_root: Path = Path("bench/results")

# ---------------------------------------------------------------------------
# run_id validation — 6-line helper duplicated from web.py contract
# (no FastAPI import in this module)
# ---------------------------------------------------------------------------

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_run_id(run_id: str) -> str | None:
    """Return an error string if run_id is invalid, else None."""
    if not _RUN_ID_RE.match(run_id):
        return f"invalid run_id {run_id!r}: must match ^[A-Za-z0-9._-]+$"
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        return f"invalid run_id {run_id!r}: path traversal not allowed"
    return None


def _run_dir(run_id: str) -> Path:
    return _runs_root / run_id


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_runs() -> list[dict[str, Any]]:
    """List all recorded runs, newest first.

    Returns a list of dicts with run_id, seed, arm, ticks, final_scores, cost.
    """
    results: list[dict[str, Any]] = []
    if not _runs_root.exists():
        return results

    run_dirs = [d for d in _runs_root.iterdir() if d.is_dir() and (d / "run.json").exists()]
    # Sort newest first by mtime
    run_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)

    for rd in run_dirs:
        try:
            manifest, ticks, _worlds = load_run(rd)
        except Exception:
            continue
        final_scores: dict[str, float] = {}
        if ticks:
            final_scores = ticks[-1].scores
        cost: dict[str, Any] = manifest.get("cost", {})
        results.append({
            "run_id": rd.name,
            "seed": manifest.get("seed"),
            "arm": manifest.get("arm"),
            "ticks": len(ticks),
            "final_scores": final_scores,
            "cost": cost,
        })
    return results


@mcp.tool()
def run_summary(run_id: str) -> dict[str, Any]:
    """Return manifest, final scores, tick count, and whether world data is present.

    Args:
        run_id: The run directory name (e.g. "scripted-seed42").
    """
    err = _validate_run_id(run_id)
    if err:
        return {"error": err}
    rd = _run_dir(run_id)
    if not rd.exists():
        return {"error": f"run {run_id!r} not found"}
    try:
        manifest, ticks, worlds = load_run(rd)
    except Exception as exc:
        return {"error": f"failed to load run: {exc}"}
    final_scores: dict[str, float] = ticks[-1].scores if ticks else {}
    return {
        "run_id": run_id,
        "manifest": manifest,
        "n_ticks": len(ticks),
        "final_scores": final_scores,
        "has_world": worlds is not None,
    }


@mcp.tool()
def get_ticks(run_id: str, start: int = 0, limit: int = 20) -> dict[str, Any]:
    """Return a page of tick records (and world states when available).

    Args:
        run_id: The run directory name.
        start: First tick index to return (0-based).
        limit: Maximum number of ticks to return. Capped at 20.
    """
    err = _validate_run_id(run_id)
    if err:
        return {"error": err}
    limit = min(limit, 20)
    rd = _run_dir(run_id)
    if not rd.exists():
        return {"error": f"run {run_id!r} not found"}
    try:
        _manifest, ticks, worlds = load_run(rd)
    except Exception as exc:
        return {"error": f"failed to load run: {exc}"}

    page = ticks[start : start + limit]
    world_page: list[dict[str, Any]] | None = None
    if worlds is not None:
        world_page = worlds[start : start + limit]

    return {
        "run_id": run_id,
        "start": start,
        "total": len(ticks),
        "ticks": [t.model_dump(mode="json") for t in page],
        "worlds": world_page,
    }


@mcp.tool()
def negotiation_feed(run_id: str, start: int = 0, limit: int = 30) -> dict[str, Any]:
    """Return human-readable lines describing proposals and their rulings.

    Each line joins a proposal to its ruling, e.g.:
      "medical requested 2 ambulance for m3 — GRANTED"
      "rescue requested 1 rescue_crew for m1 — DECLINED: pool exhausted, granted to m2"

    Args:
        run_id: The run directory name.
        start: First event index (across all ticks).
        limit: Maximum lines to return.
    """
    err = _validate_run_id(run_id)
    if err:
        return {"error": err}
    rd = _run_dir(run_id)
    if not rd.exists():
        return {"error": f"run {run_id!r} not found"}
    try:
        _manifest, ticks, _worlds = load_run(rd)
    except Exception as exc:
        return {"error": f"failed to load run: {exc}"}

    lines: list[dict[str, Any]] = []
    for record in ticks:
        # Build proposal_id -> proposal map from all agent responses
        proposals: dict[str, Any] = {}
        for resp in record.responses:
            for prop in resp.proposals:
                proposals[prop.proposal_id] = prop

        # Build ruling map
        rulings: dict[str, Any] = {r.proposal_id: r for r in record.rulings}

        for prop_id, prop in sorted(proposals.items()):
            ruling = rulings.get(prop_id)
            # Compose human-readable line
            body = prop.body
            resource = body.get("resource", "")
            qty = body.get("qty", "")
            mission_id = body.get("mission_id", "")
            kind_str = prop.kind

            if resource and mission_id:
                action = f"requested {qty} {resource} for {mission_id}"
            elif body:
                action = f"sent {kind_str} {json.dumps(body, separators=(',', ':'))}"
            else:
                action = f"sent {kind_str}"

            if ruling is None:
                outcome = "NO RULING RECORDED"
            elif ruling.accepted:
                outcome = "GRANTED"
            else:
                reason = ruling.reason or "declined"
                outcome = f"DECLINED: {reason}"

            lines.append({
                "tick": record.tick,
                "proposal_id": prop_id,
                "sender": prop.sender,
                "recipient": prop.recipient,
                "line": f"{prop.sender} {action} — {outcome}",
                "accepted": ruling.accepted if ruling else None,
                "reason": ruling.reason if ruling else "",
            })

    page = lines[start : start + limit]
    return {
        "run_id": run_id,
        "start": start,
        "total": len(lines),
        "feed": page,
    }


@mcp.tool()
def agent_story(run_id: str, agent_id: str) -> dict[str, Any]:
    """Aggregate one agent's decisions, rationales, rejections, and proposal outcomes.

    Args:
        run_id: The run directory name.
        agent_id: The agent to summarise (e.g. "medical").
    """
    err = _validate_run_id(run_id)
    if err:
        return {"error": err}
    rd = _run_dir(run_id)
    if not rd.exists():
        return {"error": f"run {run_id!r} not found"}
    try:
        _manifest, ticks, _worlds = load_run(rd)
    except Exception as exc:
        return {"error": f"failed to load run: {exc}"}

    decisions: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    proposal_outcomes: list[dict[str, Any]] = []

    for record in ticks:
        # Accepted decisions by this agent
        for dec in record.accepted:
            if dec.agent_id == agent_id:
                decisions.append({
                    "tick": record.tick,
                    "decision_id": dec.decision_id,
                    "decision_type": dec.decision_type,
                    "params": dec.params,
                    "rationale": dec.rationale,
                })

        # Rejections for this agent
        for rej in record.rejected:
            if rej.agent_id == agent_id:
                rejections.append({
                    "tick": record.tick,
                    "decision_id": rej.decision_id,
                    "decision_type": rej.decision_type,
                    "reason": rej.reason,
                })

        # Proposal outcomes for proposals sent by this agent
        agent_proposals: dict[str, Any] = {}
        for resp in record.responses:
            if resp.agent_id == agent_id:
                for prop in resp.proposals:
                    agent_proposals[prop.proposal_id] = prop

        ruling_map = {r.proposal_id: r for r in record.rulings}
        for prop_id, prop in sorted(agent_proposals.items()):
            ruling = ruling_map.get(prop_id)
            proposal_outcomes.append({
                "tick": record.tick,
                "proposal_id": prop_id,
                "kind": prop.kind,
                "body": prop.body,
                "accepted": ruling.accepted if ruling else None,
                "reason": ruling.reason if ruling else "",
            })

    return {
        "run_id": run_id,
        "agent_id": agent_id,
        "decisions": decisions,
        "rejections": rejections,
        "proposal_outcomes": proposal_outcomes,
    }


@mcp.tool()
def bench_results() -> dict[str, Any]:
    """Return parsed benchmark tables from the bench results directory.

    Scans bench_root for results.json files, newest first.
    """
    if not _bench_root.exists():
        return {"error": f"bench root {_bench_root} not found", "results": []}

    found: list[dict[str, Any]] = []
    candidates = [
        p for p in _bench_root.rglob("results.json")
        if p.is_file()
    ]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            found.append({"path": str(path), "data": data})
        except Exception as exc:
            found.append({"path": str(path), "error": str(exc)})

    return {"results": found}


@mcp.tool()
def inject_event(kind: str, district: str) -> dict[str, Any]:
    """Inject a live event into a running Aftershock server.

    POSTs to http://127.0.0.1:8788/api/live/inject.
    Returns a clear error string when no live server or live run exists.

    Args:
        kind: Event kind — one of "fire", "aftershock", "road_block".
        district: District id, e.g. "old_town", "harbor".
    """
    _server_url = os.environ.get("AFTERSHOCK_SERVER_URL", "http://127.0.0.1:8788")
    url = f"{_server_url.rstrip('/')}/api/live/inject"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(url, json={"kind": kind, "district": district})
        if resp.status_code == 200:
            return {"ok": True, "status": 200}
        elif resp.status_code == 404:
            return {"ok": False, "error": "no live run is currently active on the server"}
        elif resp.status_code == 422:
            return {"ok": False, "error": f"invalid event kind or district: {resp.text}"}
        else:
            return {"ok": False, "error": f"server returned HTTP {resp.status_code}: {resp.text}"}
    except httpx.ConnectError:
        return {
            "ok": False,
            "error": (
                "could not connect to aftershock server at 127.0.0.1:8788 — "
                "start it with: aftershock serve"
            ),
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "error": "request to aftershock server timed out (is it still running?)",
        }
    except Exception as exc:
        return {"ok": False, "error": f"unexpected error contacting server: {exc}"}


# ---------------------------------------------------------------------------
# Server factory (used by CLI and tests)
# ---------------------------------------------------------------------------


def create_server(runs_root: Path, bench_root: Path | None = None) -> FastMCP:
    """Configure the module-level MCP server and return it.

    Args:
        runs_root: Directory that holds individual run directories.
        bench_root: Directory that holds benchmark results. Defaults to bench/results.
    """
    global _runs_root, _bench_root
    _runs_root = runs_root
    if bench_root is not None:
        _bench_root = bench_root
    return mcp
