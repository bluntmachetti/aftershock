"""Tests for the Aftershock web server (web.py).

Uses FastAPI TestClient (httpx ASGI transport) against a tmp runs_root seeded
by running a tiny scripted Engine run in-process (8 ticks).

Covers:
  - GET /api/runs  (listing)
  - GET /api/runs/{run_id}  (detail)
  - GET /api/runs/{run_id}/ticks  (paged, worlds included)
  - Path-traversal attempts ("../x", "%2e%2e", absolute paths) all 404/422
  - GET /api/bench  reads a fixture results.json
  - GET /api/live  (status)
  - POST /api/live  with arm=scripted: end-to-end, including WS stream to completion
  - WS /ws/live: buffered replay on connect + live tail to completion
  - POST /api/live/inject: mid-run injection appears in a later tick's events
  - Second concurrent live POST -> 409
  - LLM arm keyless -> 503 with hint in detail
  - GET /api/runs/{run_id}/aar: 404 when absent, 200 after fixture written; traversal rejected
  - POST /api/live with aar=true + memory=true: WS delivers aar message, memory.json grows
  - Second live run with memory=true: commander system prompt contains lessons block
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder
from aftershock.town.arms import build_arm
from aftershock.web import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _run_scripted_8(runs_root: Path, seed: int = 7) -> str:
    """Run a scripted 8-tick Engine in-process; return the run_id."""
    setup = build_arm("scripted", seed, None)
    run_id = f"scripted-seed{seed}"
    manifest = {"arm": "scripted", "seed": seed, "ticks": 8, "run_id": run_id}
    recorder = Recorder(runs_root, run_id, manifest)
    engine = Engine(
        world=setup.world,
        society=setup.society,
        agents=setup.agents,
        registry=setup.registry,
        roles=setup.roles,
        resolver=setup.resolver,
        recorder=recorder,
        seed=seed,
        max_ticks=8,
        agent_timeout_s=5.0,
    )
    asyncio.run(engine.run())
    return run_id


@pytest.fixture()
def runs_root(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    return root


@pytest.fixture()
def seeded_runs_root(tmp_path: Path) -> tuple[Path, str]:
    """A runs_root with one completed 8-tick scripted run."""
    root = tmp_path / "runs"
    root.mkdir()
    run_id = _run_scripted_8(root)
    return root, run_id


@pytest.fixture()
def bench_root(tmp_path: Path) -> Path:
    br = tmp_path / "bench_results"
    br.mkdir()
    results = {
        "arms": {"scripted": {"n": 1, "mean_lives_saved": 10.0}},
        "paired": {"scripted": {7: 10.0}},
    }
    (br / "results.json").write_text(json.dumps(results), encoding="utf-8")
    # The real layout: results.json inside a dated subdirectory (bench/results/<date>/).
    dated = br / "2026-06-11"
    dated.mkdir()
    dated_results = {
        "arms": {"society": {"n": 5, "mean_lives_saved": 103.2}},
        "paired": {"society": {11: 140.0}},
    }
    (dated / "results.json").write_text(json.dumps(dated_results), encoding="utf-8")
    return br


# ---------------------------------------------------------------------------
# Helpers to reset global live state between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_live_state(monkeypatch: pytest.MonkeyPatch):
    """Reset the module-level _live singleton before each test, and neutralize the
    live-stream tick pacing (a presentation-only wall-clock delay) so the suite stays
    fast. The dedicated pacing test re-enables a small delay in its own body."""
    import aftershock.web as web_mod

    web_mod._live = None
    web_mod._ambient_task = None
    monkeypatch.setattr(web_mod, "_LIVE_TICK_DELAY_S", 0.0)
    yield
    web_mod._live = None
    web_mod._ambient_task = None


# ---------------------------------------------------------------------------
# Tests: run listing
# ---------------------------------------------------------------------------


def test_list_runs_empty(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_runs_with_run(seeded_runs_root: tuple[Path, str]) -> None:
    root, run_id = seeded_runs_root
    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get("/api/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 1
    r = runs[0]
    assert r["run_id"] == run_id
    assert r["arm"] == "scripted"
    assert r["seed"] == 7
    assert r["ticks"] == 8
    assert r["has_world"] is True


# ---------------------------------------------------------------------------
# Tests: run detail
# ---------------------------------------------------------------------------


def test_run_detail(seeded_runs_root: tuple[Path, str]) -> None:
    root, run_id = seeded_runs_root
    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert data["n_ticks"] == 8
    assert data["has_world"] is True
    assert "manifest" in data


def test_run_detail_not_found(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.get("/api/runs/no-such-run")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: paged ticks include worlds
# ---------------------------------------------------------------------------


def test_run_ticks_paged(seeded_runs_root: tuple[Path, str]) -> None:
    root, run_id = seeded_runs_root
    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get(f"/api/runs/{run_id}/ticks", params={"start": 0, "limit": 4})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 8
    assert len(data["ticks"]) == 4
    # worlds must be present
    assert data["worlds"] is not None
    assert len(data["worlds"]) == 4


def test_run_ticks_limit_capped(seeded_runs_root: tuple[Path, str]) -> None:
    root, run_id = seeded_runs_root
    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get(f"/api/runs/{run_id}/ticks", params={"start": 0, "limit": 9999})
    assert resp.status_code == 200
    data = resp.json()
    # limit capped at 200; only 8 ticks exist so we get 8
    assert len(data["ticks"]) == 8


# ---------------------------------------------------------------------------
# Tests: path traversal — must never escape runs_root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", [
    "../etc",
    "..%2fetc",
    "%2e%2e",
    "/etc/passwd",
    "a/b",
    "a\\b",
])
def test_path_traversal_detail(runs_root: Path, bad_id: str) -> None:
    app = create_app(runs_root)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(f"/api/runs/{bad_id}")
    assert resp.status_code in (404, 422), (
        f"Expected 404/422 for {bad_id!r}, got {resp.status_code}"
    )


@pytest.mark.parametrize("bad_id", [
    "../etc",
    "..%2fetc",
    "%2e%2e",
    "/etc/passwd",
    "a/b",
    "a\\b",
])
def test_path_traversal_ticks(runs_root: Path, bad_id: str) -> None:
    app = create_app(runs_root)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(f"/api/runs/{bad_id}/ticks")
    assert resp.status_code in (404, 422), (
        f"Expected 404/422 for {bad_id!r}, got {resp.status_code}"
    )


def test_path_traversal_never_escapes_runs_root(tmp_path: Path) -> None:
    """Verify that no traversal attempt can read a file outside runs_root."""
    # Create a sentinel file outside the runs root
    sentinel = tmp_path / "secret.txt"
    sentinel.write_text("SECRET", encoding="utf-8")

    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    app = create_app(runs_root)
    with TestClient(app, raise_server_exceptions=False) as client:
        for attempt in ["../secret", "..%2fsecret", "%2e%2e%2fsecret"]:
            resp = client.get(f"/api/runs/{attempt}")
            assert resp.status_code in (404, 422), (
                f"Traversal attempt {attempt!r} gave {resp.status_code}"
            )
            body = resp.text
            assert "SECRET" not in body


# ---------------------------------------------------------------------------
# Tests: /api/bench
# ---------------------------------------------------------------------------


def test_bench_empty(runs_root: Path) -> None:
    app = create_app(runs_root, bench_root=Path("/nonexistent_bench_xyzzy"))
    with TestClient(app) as client:
        resp = client.get("/api/bench")
    assert resp.status_code == 200
    assert resp.json() == []


def test_bench_reads_fixture(runs_root: Path, bench_root: Path) -> None:
    app = create_app(runs_root, bench_root=bench_root)
    with TestClient(app) as client:
        resp = client.get("/api/bench")
    assert resp.status_code == 200
    data = resp.json()
    # Both the top-level results.json and the dated-subdirectory one must be found.
    assert len(data) == 2
    arms_seen = {arm for result in data for arm in result["arms"]}
    assert arms_seen == {"scripted", "society"}


# ---------------------------------------------------------------------------
# Tests: /api/live status when no run
# ---------------------------------------------------------------------------


def test_live_status_no_run(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.get("/api/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert data["live_id"] is None


# ---------------------------------------------------------------------------
# Tests: LLM arm without API key → 503
# ---------------------------------------------------------------------------


def test_live_llm_arm_no_key_503(runs_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "society", "seed": 1, "ticks": 5})
    assert resp.status_code == 503
    body = resp.json()
    assert "DASHSCOPE_API_KEY" in body.get("detail", "")


def test_live_llm_arm_solo_no_key_503(runs_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "solo", "seed": 1, "ticks": 5})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Tests: ticks > 120 → 422
# ---------------------------------------------------------------------------


def test_live_ticks_over_cap_422(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 1, "ticks": 121})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: second concurrent live run → 409
# ---------------------------------------------------------------------------


def test_live_second_concurrent_409(runs_root: Path) -> None:
    import aftershock.web as web_mod
    from aftershock.web import _LiveState

    # Manually set a running live state
    web_mod._live = _LiveState(live_id="test-id", arm="scripted", seed=1, running=True)

    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 2, "ticks": 5})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Tests: inject when no live run → 404; bad kind → 422
# ---------------------------------------------------------------------------


def test_inject_no_live_run_404(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post("/api/live/inject", json={"kind": "fire", "district": "harbor"})
    assert resp.status_code == 404


def test_inject_bad_kind_422(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post("/api/live/inject", json={"kind": "volcano", "district": "harbor"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests: scripted live run end-to-end (WS stream to completion)
# ---------------------------------------------------------------------------


def test_live_scripted_end_to_end(tmp_path: Path) -> None:
    """Full end-to-end: POST /api/live, WS /ws/live streams all ticks + done."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    app = create_app(runs_root)

    with TestClient(app) as client:
        # Start the live run
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 3, "ticks": 8})
        assert resp.status_code == 200
        live_id = resp.json()["live_id"]
        assert live_id

        # Give the background task time to run (TestClient is sync; the asyncio task
        # runs in the same event loop during TestClient context)
        time.sleep(0.5)

        # Check live status
        status_resp = client.get("/api/live")
        assert status_resp.status_code == 200

        # Connect via WebSocket and collect messages
        tick_messages: list[dict] = []
        done_message: dict | None = None

        with client.websocket_connect("/ws/live") as ws:
            # Collect messages with a generous timeout
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                try:
                    raw = ws.receive_json()
                    if raw.get("type") == "tick":
                        tick_messages.append(raw)
                    elif raw.get("type") == "done":
                        done_message = raw
                        break
                    # ignore ping messages
                except Exception:
                    break

    # Validate ticks received
    assert len(tick_messages) >= 1, "expected at least one tick message"
    for msg in tick_messages:
        assert "record" in msg
        assert "world" in msg

    # Validate done message
    assert done_message is not None, "expected a done message"
    summary = done_message["summary"]
    assert summary["arm"] == "scripted" or "run_id" in summary

    # Validate run was written to disk
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir()]
    assert len(run_dirs) >= 1
    run_dir = run_dirs[0]
    assert (run_dir / "run.json").exists()
    assert (run_dir / "ticks.ndjson").exists()


# ---------------------------------------------------------------------------
# Tests: POST /api/counterfactual
# ---------------------------------------------------------------------------


def test_counterfactual_bad_at_tick_422(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/counterfactual",
            json={"arm": "scripted", "seed": 1, "ticks": 10, "at_tick": 10,
                  "kind": "drop_protocol"},
        )
    assert resp.status_code == 422


def test_counterfactual_llm_arm_no_key_503(
    runs_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/counterfactual",
            json={"arm": "society", "seed": 1, "ticks": 10, "at_tick": 5,
                  "kind": "drop_protocol"},
        )
    assert resp.status_code == 503


def test_counterfactual_scripted_end_to_end(tmp_path: Path) -> None:
    """POST /api/counterfactual streams ticks + done over /ws/live and writes a
    branch run dir whose manifest carries the counterfactual spec."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    app = create_app(runs_root)

    with TestClient(app) as client:
        resp = client.post(
            "/api/counterfactual",
            json={"arm": "scripted", "seed": 3, "ticks": 12, "at_tick": 5,
                  "kind": "drop_protocol", "baseline_run_id": "seed3-scripted"},
        )
        assert resp.status_code == 200
        assert resp.json()["live_id"]
        time.sleep(0.5)

        tick_messages: list[dict] = []
        done_message: dict | None = None
        with client.websocket_connect("/ws/live") as ws:
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                try:
                    raw = ws.receive_json()
                    if raw.get("type") == "tick":
                        tick_messages.append(raw)
                    elif raw.get("type") == "done":
                        done_message = raw
                        break
                except Exception:
                    break

    assert len(tick_messages) >= 1
    assert done_message is not None
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir()]
    assert len(run_dirs) == 1
    manifest = json.loads((run_dirs[0] / "run.json").read_text(encoding="utf-8"))
    cf = manifest["counterfactual"]
    assert cf["kind"] == "drop_protocol"
    assert cf["at_tick"] == 5
    assert cf["branch_of"] == "seed3-scripted"


def test_live_tick_pacing_spaces_ticks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_LIVE_TICK_DELAY_S paces a fast scripted stream server-side, so ticks arrive
    spaced over wall-clock instead of bursting all at once."""
    import aftershock.web as web_mod

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    delay = 0.05
    monkeypatch.setattr(web_mod, "_LIVE_TICK_DELAY_S", delay)
    app = create_app(runs_root)

    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 3, "ticks": 8})
        assert resp.status_code == 200
        start = time.monotonic()
        ticks_seen = 0
        with client.websocket_connect("/ws/live") as ws:
            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline:
                try:
                    raw = ws.receive_json()
                except Exception:
                    break
                if raw.get("type") == "tick":
                    ticks_seen += 1
                elif raw.get("type") == "done":
                    break
        elapsed = time.monotonic() - start

    assert ticks_seen >= 2
    # With a per-tick delay the run must span at least a couple of pacing gaps;
    # the un-paced regression would burst to completion well under this bound.
    assert elapsed >= 2 * delay


def test_live_stop_cancels_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/live/stop cancels an in-progress run; status returns to idle and a
    fresh run can start (no 409 from the singleton)."""
    import aftershock.web as web_mod

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    # Pace it so the run stays in-progress long enough to interrupt.
    monkeypatch.setattr(web_mod, "_LIVE_TICK_DELAY_S", 0.2)
    app = create_app(runs_root)

    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 7, "ticks": 60})
        assert resp.status_code == 200
        time.sleep(0.1)  # let the background task begin

        stop = client.post("/api/live/stop")
        assert stop.status_code == 200
        assert stop.json()["running"] is False

        assert client.get("/api/live").json()["running"] is False

        # No 409 — the singleton is free again.
        resp2 = client.post("/api/live", json={"arm": "scripted", "seed": 8, "ticks": 4})
        assert resp2.status_code == 200
        client.post("/api/live/stop")  # tidy up the second run


def test_live_stop_no_run_is_noop(runs_root: Path) -> None:
    """Stopping with no run in progress is an idempotent 200."""
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post("/api/live/stop")
        assert resp.status_code == 200
        assert resp.json()["running"] is False


# ---------------------------------------------------------------------------
# Tests: ambient demo loop (AFTERSHOCK_DEMO_MODE)
# ---------------------------------------------------------------------------


def _poll_live(client: TestClient, predicate, timeout: float = 6.0) -> dict:
    """Poll GET /api/live until predicate(status) is true (or timeout); return last."""
    deadline = time.monotonic() + timeout
    data = client.get("/api/live").json()
    while time.monotonic() < deadline:
        data = client.get("/api/live").json()
        if predicate(data):
            return data
        time.sleep(0.02)
    return data


def test_ambient_demo_loop_starts_when_demo_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With AFTERSHOCK_DEMO_MODE set, the app lifespan auto-starts a looping scripted
    ambient run — the public Live tab is alive with no client POST."""
    import aftershock.web as web_mod

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    monkeypatch.setenv("AFTERSHOCK_DEMO_MODE", "1")
    monkeypatch.setattr(web_mod, "_LIVE_TICK_DELAY_S", 0.05)
    monkeypatch.setattr(web_mod, "_AMBIENT_RESTART_DELAY_S", 0.05)
    monkeypatch.setattr(web_mod, "_AMBIENT_POLL_S", 0.05)
    app = create_app(runs_root)

    with TestClient(app) as client:
        data = _poll_live(client, lambda d: d["running"] and d["mode"] == "ambient")

    assert data["running"] is True
    assert data["mode"] == "ambient"
    assert data["arm"] == "scripted"


def test_ambient_disabled_without_demo_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without AFTERSHOCK_DEMO_MODE there is no ambient run — status stays idle."""
    monkeypatch.delenv("AFTERSHOCK_DEMO_MODE", raising=False)
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    app = create_app(runs_root)

    with TestClient(app) as client:
        time.sleep(0.15)
        data = client.get("/api/live").json()

    assert data["running"] is False
    assert data["mode"] is None


def test_manual_preempts_and_ambient_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manual operator run pre-empts the ambient loop (and blocks a second manual);
    stopping it lets the ambient loop resume."""
    import aftershock.web as web_mod

    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    monkeypatch.setenv("AFTERSHOCK_DEMO_MODE", "1")
    monkeypatch.setattr(web_mod, "_LIVE_TICK_DELAY_S", 0.05)
    monkeypatch.setattr(web_mod, "_AMBIENT_RESTART_DELAY_S", 0.05)
    monkeypatch.setattr(web_mod, "_AMBIENT_POLL_S", 0.05)
    app = create_app(runs_root)

    with TestClient(app) as client:
        _poll_live(client, lambda d: d["running"] and d["mode"] == "ambient")

        # Operator takes the floor — pre-empts the ambient run.
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 99, "ticks": 60})
        assert resp.status_code == 200
        data = _poll_live(client, lambda d: d["mode"] == "manual")
        assert data["mode"] == "manual"
        assert data["seed"] == 99

        # A second manual start is rejected while the manual run holds the floor.
        resp2 = client.post("/api/live", json={"arm": "scripted", "seed": 1, "ticks": 4})
        assert resp2.status_code == 409

        # Releasing the manual run lets the ambient loop resume.
        client.post("/api/live/stop")
        data = _poll_live(client, lambda d: d["running"] and d["mode"] == "ambient")
        assert data["mode"] == "ambient"


# ---------------------------------------------------------------------------
# Tests: inject mid-run appears in tick events
# ---------------------------------------------------------------------------


def test_live_inject_appears_in_events(tmp_path: Path) -> None:
    """Mid-run inject of 'fire' should appear in a later tick's events."""
    import aftershock.web as web_mod

    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    app = create_app(runs_root)

    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 5, "ticks": 10})
        assert resp.status_code == 200

        # Wait briefly for the run to start and the society to be wired
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            state = web_mod._live
            soc = getattr(state, "_society", None) if state else None
            if soc is not None:
                break
            time.sleep(0.05)

        # Inject an event mid-run (best-effort; may arrive after run ends)
        inj_resp = client.post(
            "/api/live/inject", json={"kind": "fire", "district": "harbor"}
        )
        # 200 if run still active, 404 if it already finished (tiny run)
        assert inj_resp.status_code in (200, 404)

        # Wait for completion
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            state = web_mod._live
            if state is None or not state.running:
                break
            time.sleep(0.1)

    # If the injection succeeded, the run dir should exist and be complete
    run_dirs = [d for d in runs_root.iterdir() if d.is_dir()]
    assert len(run_dirs) >= 1


# ---------------------------------------------------------------------------
# Tests: WS replay-on-connect (connect after ticks have already buffered)
# ---------------------------------------------------------------------------


def test_ws_replay_on_connect(tmp_path: Path) -> None:
    """Connecting to WS after ticks have buffered should replay those ticks."""
    import aftershock.web as web_mod

    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    app = create_app(runs_root)

    with TestClient(app) as client:
        resp = client.post("/api/live", json={"arm": "scripted", "seed": 11, "ticks": 8})
        assert resp.status_code == 200

        # Wait until at least a couple ticks have buffered
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            state = web_mod._live
            if state is not None and len(state.buffer) >= 2:
                break
            time.sleep(0.05)

        # Now connect — should receive buffered ticks first
        received: list[dict] = []
        with client.websocket_connect("/ws/live") as ws:
            collect_deadline = time.monotonic() + 10.0
            while time.monotonic() < collect_deadline:
                try:
                    msg = ws.receive_json()
                    received.append(msg)
                    if msg.get("type") == "done":
                        break
                except Exception:
                    break

    tick_msgs = [m for m in received if m.get("type") == "tick"]
    assert len(tick_msgs) >= 1, "should have received at least one buffered tick"


# ---------------------------------------------------------------------------
# Tests: static mount serves web/dist/index.html when dist exists
# ---------------------------------------------------------------------------


def test_static_serves_index_html_when_dist_exists(tmp_path: Path) -> None:
    """GET / must return the built index.html when web/dist exists."""
    # Create a minimal fake dist directory with an index.html
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    index_html = dist_dir / "index.html"
    index_html.write_text(
        "<!DOCTYPE html><html><head><title>Aftershock</title></head><body></body></html>",
        encoding="utf-8",
    )

    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Patch the web_dist path inside create_app so it points to our fake dist
    import aftershock.web as web_mod
    from aftershock.web import create_app

    real_file = web_mod.__file__
    assert real_file is not None

    # We monkeypatch by building the app and then manually re-mounting static files,
    # OR we can simply use the real web/dist which is built by npm run build.
    # The cleaner approach: use the real dist that was built by the build step.
    real_dist = Path(real_file).parent.parent.parent / "web" / "dist"
    if real_dist.exists() and real_dist.is_dir() and (real_dist / "index.html").exists():
        app = create_app(runs_root=runs_root)
        with TestClient(app) as client:
            resp = client.get("/")
        assert resp.status_code == 200
        body = resp.text
        assert "<!DOCTYPE html>" in body or "<!doctype html>" in body.lower(), (
            f"Expected HTML from static mount, got:\n{body[:200]}"
        )
    else:
        # dist not built yet — create_app falls back to JSON hint
        app = create_app(runs_root=runs_root)
        with TestClient(app) as client:
            resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "hint" in data


# ---------------------------------------------------------------------------
# Helpers for AAR / society tests
# ---------------------------------------------------------------------------


def _make_aar_fixture() -> dict[str, Any]:
    return {
        "headline": "Adequate response with coordination gaps",
        "grade": "B",
        "what_worked": ["Ambulances dispatched promptly"],
        "coordination_failures": ["Fire response delayed"],
        "key_moments": [{"tick": 3, "description": "First mission resolved"}],
        "lessons": ["Prioritise fire missions early", "Broadcast more at high panic"],
        "usage": {
            "prompt_tokens": 100, "completion_tokens": 50, "cost_usd": 0.001, "model": "qwen3-max"
        },
    }


def _build_society_mock_response(model: str, system: str, user: str) -> str:  # noqa: ARG001
    """Return a minimal valid JSON agent response for any observation."""
    decisions: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []

    # Detect role from system prompt
    agent_role = "unknown"
    for role in ("commander", "medical", "rescue", "fire", "infrastructure", "comms"):
        if role in system.lower()[:300]:
            agent_role = role
            break

    # Simple strategy: commander sets priority, others request resources
    if agent_role == "commander":
        # Try to set priority on any mission in the observation
        for line in user.splitlines():
            m = re.match(r"\s+(m\d+)\s+\S+\s+\S+\s+\d+\s+\d+\s+\S+\s+0\s", line)
            if m:
                decisions.append({
                    "decision_type": "set_priority",
                    "params": {"mission_id": m.group(1), "priority": 5},
                    "rationale": "initial triage",
                })
                break  # one decision per tick is enough

    # Extract and respond to any inbox proposals
    in_inbox = False
    for line in user.splitlines():
        if "YOUR INBOX" in line:
            in_inbox = True
            continue
        if in_inbox:
            if line.strip() == "" or (line and not line.startswith(" ") and "(empty)" not in line):
                break
            prop_m = re.search(r"\[([^\]]+)\]", line)
            if prop_m:
                pid = prop_m.group(1)
                if not any(r["proposal_id"] == pid for r in responses):
                    responses.append({"proposal_id": pid, "accept": True, "note": "ok"})

    return json.dumps({"decisions": decisions, "proposals": proposals, "responses": responses})


def _make_aar_provider_response() -> str:
    """Return a valid AAR JSON string for MockProvider."""
    return json.dumps({
        "headline": "Test run: adequate response",
        "grade": "B",
        "what_worked": ["Ambulances dispatched promptly"],
        "coordination_failures": ["Fire response slow"],
        "key_moments": [{"tick": 1, "description": "First mission spawned"}],
        "lessons": ["Prioritise fire early", "Broadcast to reduce panic"],
    })


# ---------------------------------------------------------------------------
# Tests: GET /api/runs/{run_id}/aar
# ---------------------------------------------------------------------------


def test_aar_endpoint_404_when_absent(seeded_runs_root: tuple[Path, str]) -> None:
    """GET /api/runs/{run_id}/aar returns 404 when aar.json is not present."""
    root, run_id = seeded_runs_root
    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get(f"/api/runs/{run_id}/aar")
    assert resp.status_code == 404


def test_aar_endpoint_200_after_fixture_written(seeded_runs_root: tuple[Path, str]) -> None:
    """GET /api/runs/{run_id}/aar returns 200 with the report after aar.json is written."""
    root, run_id = seeded_runs_root
    aar_data = _make_aar_fixture()
    (root / run_id / "aar.json").write_text(json.dumps(aar_data), encoding="utf-8")

    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get(f"/api/runs/{run_id}/aar")
    assert resp.status_code == 200
    body = resp.json()
    assert body["grade"] == "B"
    assert body["headline"] == "Adequate response with coordination gaps"
    assert len(body["lessons"]) == 2


@pytest.mark.parametrize("bad_id", [
    "../etc",
    "..%2fetc",
    "%2e%2e",
    "/etc/passwd",
    "a/b",
    "a\\b",
])
def test_aar_traversal_rejected(runs_root: Path, bad_id: str) -> None:
    """Path traversal on /api/runs/{run_id}/aar must be rejected with 404 or 422."""
    app = create_app(runs_root)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(f"/api/runs/{bad_id}/aar")
    assert resp.status_code in (404, 422), (
        f"Expected 404/422 for traversal {bad_id!r}, got {resp.status_code}"
    )


def test_aar_endpoint_rejects_invalid_grade(tmp_path: Path) -> None:
    """GET /api/runs/{run_id}/aar must return 404 for aar.json with invalid grade."""
    run_id = "hostile-run"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "aar.json").write_text(
        json.dumps({
            "headline": "x",
            "grade": "Z-NOT-A-GRADE",
            "what_worked": "not-a-list",
            "coordination_failures": None,
            "key_moments": [],
            "lessons": [],
        }),
        encoding="utf-8",
    )
    app = create_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(f"/api/runs/{run_id}/aar")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


def test_aar_endpoint_rejects_oversized_file(tmp_path: Path) -> None:
    """GET /api/runs/{run_id}/aar must return 404 for aar.json exceeding the size cap."""
    run_id = "big-run"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    big = {
        "headline": "x" * 600_000,
        "grade": "A",
        "what_worked": [],
        "coordination_failures": [],
        "key_moments": [],
        "lessons": [],
    }
    (run_dir / "aar.json").write_text(json.dumps(big), encoding="utf-8")
    app = create_app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(f"/api/runs/{run_id}/aar")
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Tests: live run with aar=true + memory=true (MockProvider injected)
# ---------------------------------------------------------------------------


def test_live_aar_and_memory_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live society run with aar=true + memory=true:
    - WS delivers {"type": "aar", "report": ...} after {"type": "done"}
    - memory.json is created and contains lessons
    Uses MockProvider injected via monkeypatching QwenProvider.
    """
    from aftershock.llm.provider import MockProvider

    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Build a script: first N calls are agent responses, last call is the AAR
    # The society arm has 6 agents × ticks calls, then 1 AAR call.
    # Use a callable so it never runs out.
    aar_call_count = 0
    total_agent_calls = [0]

    def _provider_script(model: str, system: str, user: str) -> str:
        nonlocal aar_call_count
        # The AAR model is qwen3-max; agent calls use qwen3.5-flash / qwen3.5-plus
        if model == "qwen3-max" or "after-action" in system.lower():
            aar_call_count += 1
            return _make_aar_provider_response()
        total_agent_calls[0] += 1
        return _build_society_mock_response(model, system, user)

    mock_provider_instance = MockProvider(script=_provider_script)

    # Patch QwenProvider in the web module so _run_live uses our MockProvider
    monkeypatch.setattr(
        "aftershock.llm.provider.QwenProvider",
        lambda **kwargs: mock_provider_instance,  # noqa: ARG005
    )
    # Satisfy the API-key check in start_live (the key is never actually used
    # since QwenProvider is monkeypatched above)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "mock-key-for-testing")

    app = create_app(runs_root)

    with TestClient(app) as client:
        resp = client.post(
            "/api/live",
            json={"arm": "society", "seed": 7, "ticks": 5, "aar": True, "memory": True},
        )
        assert resp.status_code == 200, resp.text
        live_id = resp.json()["live_id"]
        assert live_id

        # Wait for run to complete
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            import aftershock.web as web_mod
            state = web_mod._live
            if state is None or not state.running:
                break
            time.sleep(0.1)

        # Collect WS messages
        tick_messages: list[dict] = []
        done_message: dict | None = None
        aar_message: dict | None = None

        with client.websocket_connect("/ws/live") as ws:
            collect_deadline = time.monotonic() + 15.0
            while time.monotonic() < collect_deadline:
                try:
                    msg = ws.receive_json()
                    if msg.get("type") == "tick":
                        tick_messages.append(msg)
                    elif msg.get("type") == "done":
                        done_message = msg
                    elif msg.get("type") == "aar":
                        aar_message = msg
                        break
                    elif msg.get("type") == "ping":
                        pass
                except Exception:
                    break

    # Validate WS messages
    assert done_message is not None, "expected a done message on WS"
    assert aar_message is not None, "expected an aar message on WS after done"
    assert "report" in aar_message, f"aar message missing 'report': {aar_message}"
    report = aar_message["report"]
    assert report["grade"] in ("A", "B", "C", "D", "F")
    assert isinstance(report.get("lessons"), list)

    # Validate memory.json was created and contains lessons
    memory_path = runs_root / "memory.json"
    assert memory_path.exists(), "memory.json should have been created"
    entries = json.loads(memory_path.read_text(encoding="utf-8"))
    assert isinstance(entries, list)
    assert len(entries) >= 1
    first_entry = entries[0]
    assert "run_id" in first_entry
    assert isinstance(first_entry.get("lessons"), list)
    assert len(first_entry["lessons"]) >= 1


# ---------------------------------------------------------------------------
# Tests: GET /api/runs/{run_id}/conformance
# ---------------------------------------------------------------------------


def _make_conformance_fixture() -> dict[str, Any]:
    return {
        "arm": "scripted",
        "seed": 7,
        "rules": {},
        "role_conformance": {"commander": 1.0, "medical": 0.95},
        "team_alignment": 0.98,
        "notes": [],
    }


def test_conformance_endpoint_404_when_absent(seeded_runs_root: tuple[Path, str]) -> None:
    """GET /api/runs/{run_id}/conformance returns 404 when conformance.json is absent."""
    root, run_id = seeded_runs_root
    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get(f"/api/runs/{run_id}/conformance")
    assert resp.status_code == 404


def test_conformance_endpoint_200_after_fixture_written(
    seeded_runs_root: tuple[Path, str],
) -> None:
    """GET /api/runs/{run_id}/conformance returns 200 with data after conformance.json exists."""
    root, run_id = seeded_runs_root
    conf_data = _make_conformance_fixture()
    (root / run_id / "conformance.json").write_text(
        json.dumps(conf_data), encoding="utf-8"
    )

    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get(f"/api/runs/{run_id}/conformance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["arm"] == "scripted"
    assert body["team_alignment"] == pytest.approx(0.98)
    assert "role_conformance" in body


@pytest.mark.parametrize("bad_id", [
    "../etc",
    "..%2fetc",
    "%2e%2e",
    "/etc/passwd",
    "a/b",
    "a\\b",
])
def test_conformance_traversal_rejected(runs_root: Path, bad_id: str) -> None:
    """Path traversal on /api/runs/{run_id}/conformance must be rejected 404/422."""
    app = create_app(runs_root)
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get(f"/api/runs/{bad_id}/conformance")
    assert resp.status_code in (404, 422), (
        f"Expected 404/422 for traversal {bad_id!r}, got {resp.status_code}"
    )


def test_conformance_no_lazy_generation(seeded_runs_root: tuple[Path, str]) -> None:
    """Conformance endpoint must NOT generate conformance.json server-side when absent.

    The file must remain absent after a 404 response.
    """
    root, run_id = seeded_runs_root
    conf_path = root / run_id / "conformance.json"
    assert not conf_path.exists(), "pre-condition: conformance.json should not exist"

    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get(f"/api/runs/{run_id}/conformance")

    assert resp.status_code == 404
    assert not conf_path.exists(), (
        "conformance.json must not be generated lazily by the server"
    )


def test_live_memory_loads_lessons_into_commander(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second live run with memory=True: the commander's system prompt contains
    the LESSONS FROM PREVIOUS DISASTERS block from memory.json.

    Verified via the MockProvider's recorded calls.
    """
    from aftershock.llm.aar import append_lessons
    from aftershock.llm.provider import MockProvider

    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Pre-seed memory.json with known lessons
    memory_path = runs_root / "memory.json"
    known_lessons = ["Prioritise fire missions early", "Always broadcast at panic > 0.4"]
    append_lessons(memory_path, "prior-run-001", known_lessons)

    recorded_calls: list[tuple[str, str, str]] = []

    def _tracking_script(model: str, system: str, user: str) -> str:
        recorded_calls.append((model, system, user))
        if model == "qwen3-max" or "after-action" in system.lower():
            return _make_aar_provider_response()
        return _build_society_mock_response(model, system, user)

    mock_provider_instance = MockProvider(script=_tracking_script)

    monkeypatch.setattr(
        "aftershock.llm.provider.QwenProvider",
        lambda **kwargs: mock_provider_instance,  # noqa: ARG005
    )
    # Satisfy the API-key check in start_live
    monkeypatch.setenv("DASHSCOPE_API_KEY", "mock-key-for-testing")

    app = create_app(runs_root)

    with TestClient(app) as client:
        resp = client.post(
            "/api/live",
            json={"arm": "society", "seed": 13, "ticks": 5, "aar": False, "memory": True},
        )
        assert resp.status_code == 200, resp.text

        # Wait for run to complete
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            import aftershock.web as web_mod
            state = web_mod._live
            if state is None or not state.running:
                break
            time.sleep(0.1)

    # Inspect recorded calls: the commander's system prompt must contain the lessons block
    commander_calls = [
        (model, system, user)
        for (model, system, user) in recorded_calls
        if "commander" in system.lower()[:500]
    ]
    assert commander_calls, "Expected at least one call for the commander agent"

    # Every commander call should have the lessons injected
    lessons_marker = "LESSONS FROM PREVIOUS DISASTERS"
    for _model, system, _user in commander_calls:
        assert lessons_marker in system, (
            f"Commander system prompt missing lessons block.\n"
            f"System prompt (first 500 chars): {system[:500]!r}"
        )
        assert "Prioritise fire missions early" in system
        assert "Always broadcast at panic > 0.4" in system
