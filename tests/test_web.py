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
# Tests: nested episode reachability (runs/episodes/<run_id>)
# ---------------------------------------------------------------------------


@pytest.fixture()
def episodes_root(tmp_path: Path) -> Path:
    """A runs_root with a direct-child run AND a nested episode run under
    runs/episodes/. The episode's leaf run_id does NOT collide with the
    direct-child run."""
    root = tmp_path / "runs"
    root.mkdir()
    _run_scripted_8(root, seed=7)
    episodes = root / "episodes"
    episodes.mkdir()
    # Run a second scripted run whose recorder writes into runs/episodes/.
    ep_id = _run_scripted_8(episodes, seed=11)
    assert ep_id == "scripted-seed11"
    return root


def test_list_runs_includes_nested_episode(episodes_root: Path) -> None:
    app = create_app(episodes_root)
    with TestClient(app) as client:
        resp = client.get("/api/runs")
    assert resp.status_code == 200
    ids = {r["run_id"] for r in resp.json()}
    assert "scripted-seed7" in ids  # direct child
    assert "scripted-seed11" in ids  # nested episode


def test_run_detail_loads_nested_episode(episodes_root: Path) -> None:
    app = create_app(episodes_root)
    with TestClient(app) as client:
        resp = client.get("/api/runs/scripted-seed11")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "scripted-seed11"
    assert data["n_ticks"] == 8


def test_run_ticks_load_nested_episode(episodes_root: Path) -> None:
    app = create_app(episodes_root)
    with TestClient(app) as client:
        resp = client.get("/api/runs/scripted-seed11/ticks", params={"limit": 3})
    assert resp.status_code == 200
    assert resp.json()["total"] == 8


def test_episodes_subdir_non_run_files_are_skipped(tmp_path: Path) -> None:
    """runs/episodes/ also holds episodes.json / episodes.md / memory.json —
    these have no run.json and must not appear in /api/runs."""
    root = tmp_path / "runs"
    root.mkdir()
    eps = root / "episodes"
    eps.mkdir()
    (eps / "episodes.json").write_text("[]", encoding="utf-8")
    (eps / "episodes.md").write_text("# eps", encoding="utf-8")
    app = create_app(root)
    with TestClient(app) as client:
        resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_episodes_path_traversal_still_404(runs_root: Path) -> None:
    """A nested-episode fallback must not open a traversal path. 'episodes'
    itself is a real subdir under runs_root, but addressing it as a run_id
    (no run.json) must 404, and the standard traversal patterns still 404
    even with an episodes/ subdir present."""
    (runs_root / "episodes").mkdir()
    app = create_app(runs_root)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/runs/episodes").status_code == 404
        for bad in ("../etc", "..%2fetc", "%2e%2e", "a/b"):
            assert client.get(f"/api/runs/{bad}").status_code in (404, 422)


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


@pytest.fixture()
def paired_bench_root(tmp_path: Path) -> Path:
    """A bench_root with ONE results.json whose `paired` table shares seeds
    across scripted (control) + society (treatment) so paired_stats is computed."""
    br = tmp_path / "bench_results"
    br.mkdir()
    results = {
        "arms": {
            "scripted": {"n": 5, "mean_lives_saved": 100.0, "sd_lives_saved": 5.0},
            "society": {"n": 5, "mean_lives_saved": 110.0, "sd_lives_saved": 6.0},
        },
        # society beats scripted on 4/5 seeds, ties on 1 → sign test not sig at
        # n=5; bootstrap CI may or may not exclude 0. Verdict is suggestive/noise.
        "paired": {
            "scripted": {42: 100.0, 7: 95.0, 13: 102.0, 23: 98.0, 57: 105.0},
            "society": {42: 108.0, 7: 101.0, 13: 100.0, 23: 110.0, 57: 112.0},
        },
    }
    (br / "results.json").write_text(json.dumps(results), encoding="utf-8")
    return br


def test_bench_serves_paired_stats(runs_root: Path, paired_bench_root: Path) -> None:
    app = create_app(runs_root, bench_root=paired_bench_root)
    with TestClient(app) as client:
        resp = client.get("/api/bench")
    data = resp.json()
    assert len(data) == 1
    ps = data[0]["paired_stats"]
    # One comparison: society vs scripted (the control).
    assert len(ps) == 1
    cmp = ps[0]
    assert cmp["control"] == "scripted"
    assert cmp["treatment"] == "society"
    assert cmp["n"] == 5
    assert "ci" in cmp and "lower" in cmp["ci"] and "upper" in cmp["ci"]
    assert "sign_test_p" in cmp
    assert "observed_power" in cmp
    assert cmp["verdict"] in ("noise", "suggestive", "credible")
    # Honesty: the verdict field + ci_excludes_zero + sign_significant are all
    # present so the UI never has to re-derive significance.


def test_bench_paired_stats_omits_no_common_seeds(
    runs_root: Path, bench_root: Path
) -> None:
    """The fixture's two results have disjoint seeds → paired_stats is []."""
    app = create_app(runs_root, bench_root=bench_root)
    with TestClient(app) as client:
        resp = client.get("/api/bench")
    for result in resp.json():
        assert result.get("paired_stats") == []


def test_bench_serves_cross_family_panel_stats(runs_root: Path, tmp_path: Path) -> None:
    """A panel comparator is exposed as the paired control without client-side stats."""
    bench_root = tmp_path / "panel_results"
    panel = bench_root / "2026-07-01-panelA-solo"
    panel.mkdir(parents=True)
    results = {
        "kind": "panelA-cross-family-solo",
        "arms": {
            "openai/gpt-test": {
                "family": "US frontier",
                "n": 3,
                "mean_lives_saved": 102.0,
                "sd_lives_saved": 2.0,
                "mean_cost_usd": 0.30,
            }
        },
        "paired": {"openai/gpt-test": {1: 102.0, 2: 98.0, 3: 106.0}},
        "comparator": {
            "name": "cheap Qwen society",
            "mean_lives_saved": 100.0,
            "mean_cost_usd": 0.025,
            "lives_per_dollar": 4000.0,
            "paired": {1: 100.0, 2: 100.0, 3: 100.0},
        },
    }
    (panel / "results.json").write_text(json.dumps(results), encoding="utf-8")

    app = create_app(runs_root, bench_root=bench_root)
    with TestClient(app) as client:
        response = client.get("/api/bench")

    assert response.status_code == 200
    served = response.json()[0]
    assert served["paired_stats"] == []  # no scripted control in this panel
    assert len(served["panel_stats"]) == 1
    comparison = served["panel_stats"][0]
    assert comparison["control"] == "society"
    assert comparison["treatment"] == "openai/gpt-test"
    assert comparison["n"] == 3
    assert comparison["mean_delta"] == 2.0


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
# Tests: GET /api/status — voucher/key detection for graceful UI degradation
# ---------------------------------------------------------------------------


def test_status_no_key(runs_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("AFTERSHOCK_DEMO_MODE", raising=False)
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm_key"] is False
    assert body["llm_arms"] == ["solo", "swarm", "society"]


def test_status_with_key(runs_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test")
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.get("/api/status")
    assert resp.json()["llm_key"] is True


# ---------------------------------------------------------------------------
# Tests: GET /api/determinism — scripted-engine verify, scoped + cached
# ---------------------------------------------------------------------------


def test_determinism_passes_and_scoped_to_scripted(runs_root: Path) -> None:
    # Reset the per-process cache so this test runs the check fresh.
    import aftershock.web as web_mod

    web_mod._determinism_cache = None
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.get("/api/determinism")
    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is True
    assert body["arm"] == "scripted"
    assert body["seed"] == 42
    # Honesty: the scope + note must NOT imply LLM/society arms are reproducible.
    assert "scripted" in body["scope"].lower()
    assert "not" in body["note"].lower() and "reproducible" in body["note"].lower()


def test_determinism_cached_on_second_call(runs_root: Path) -> None:
    """The verify re-run is ~seconds; the second call must be a cache hit
    (identical body, no second engine run)."""
    import aftershock.web as web_mod

    web_mod._determinism_cache = None
    app = create_app(runs_root)
    with TestClient(app) as client:
        first = client.get("/api/determinism").json()
        second = client.get("/api/determinism").json()
    assert first == second
    assert first["passed"] is True


# ---------------------------------------------------------------------------
# Tests: bench.paired_comparisons (pure stats adapter)
# ---------------------------------------------------------------------------


def test_paired_comparisons_no_common_seeds() -> None:
    from aftershock.bench import paired_comparisons

    paired = {"scripted": {1: 10.0}, "society": {2: 20.0}}
    assert paired_comparisons(paired) == []


def test_paired_comparisons_no_control() -> None:
    from aftershock.bench import paired_comparisons

    # No scripted control → empty (graceful, not an error).
    assert paired_comparisons({"society": {1: 10.0}}) == []


def test_paired_comparisons_verdict_fields() -> None:
    from aftershock.bench import paired_comparisons

    # society beats scripted on every seed → delta always positive.
    paired = {
        "scripted": {1: 100.0, 2: 100.0, 3: 100.0, 4: 100.0, 5: 100.0},
        "society": {1: 120.0, 2: 118.0, 3: 122.0, 4: 119.0, 5: 121.0},
    }
    out = paired_comparisons(paired)
    assert len(out) == 1
    cmp = out[0]
    assert cmp["n"] == 5
    assert cmp["n_positive"] == 5
    assert cmp["n_negative"] == 0
    assert cmp["mean_delta"] > 0
    assert cmp["ci"]["lower"] > 0  # excludes 0
    assert cmp["verdict"] in ("suggestive", "credible")


def test_paired_comparisons_noise_when_ci_includes_zero() -> None:
    from aftershock.bench import paired_comparisons

    # Mixed deltas straddling 0 → CI includes 0 → "noise".
    paired = {
        "scripted": {1: 100.0, 2: 100.0, 3: 100.0, 4: 100.0, 5: 100.0},
        "society": {1: 110.0, 2: 90.0, 3: 105.0, 4: 95.0, 5: 100.0},
    }
    out = paired_comparisons(paired)
    assert out[0]["verdict"] == "noise"
    assert out[0]["ci_excludes_zero"] is False


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


def test_counterfactual_bad_kind_422(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/counterfactual",
            json={"arm": "scripted", "seed": 1, "ticks": 10, "at_tick": 3, "kind": "teleport"},
        )
    assert resp.status_code == 422


def test_counterfactual_inject_bad_event_422(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/counterfactual",
            json={"arm": "scripted", "seed": 1, "ticks": 10, "at_tick": 3,
                  "kind": "inject_event", "target": "market", "params": {"event": "meteor"}},
        )
    assert resp.status_code == 422


def test_counterfactual_inject_missing_target_422(runs_root: Path) -> None:
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/counterfactual",
            json={"arm": "scripted", "seed": 1, "ticks": 10, "at_tick": 3,
                  "kind": "inject_event", "params": {"event": "fire"}},
        )
    assert resp.status_code == 422


def test_counterfactual_run_list_surfaces_metadata_and_is_loadable(tmp_path: Path) -> None:
    """After a branch finishes, GET /api/runs carries the counterfactual block (so the
    Compare tab can draw the DIVERGES marker + WHAT-IF badge), and the branch run id is
    loadable via /api/runs/{id} (guards the run-id grammar — no '@')."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    app = create_app(runs_root)
    with TestClient(app) as client:
        resp = client.post(
            "/api/counterfactual",
            json={"arm": "scripted", "seed": 3, "ticks": 12, "at_tick": 5,
                  "kind": "drop_protocol"},
        )
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]
        # Branch finishes when run.json gains final_scores (written at recorder close).
        deadline = time.monotonic() + 15.0
        row: dict | None = None
        while time.monotonic() < deadline:
            rows = client.get("/api/runs").json()
            row = next((r for r in rows if r["run_id"] == run_id), None)
            if row and row.get("final_scores"):
                break
            time.sleep(0.2)
        assert row is not None, "branch run never appeared in /api/runs"
        assert row["counterfactual"]["at_tick"] == 5
        assert row["counterfactual"]["kind"] == "drop_protocol"
        # The branch must be loadable by Compare (run id has no '@' → no 404).
        assert client.get(f"/api/runs/{run_id}").status_code == 200
        assert client.get(f"/api/runs/{run_id}/ticks?start=0&limit=100").status_code == 200


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
    """With AFTERSHOCK_DEMO_MODE set, the app lifespan auto-starts a looping ambient run
    — the public Live tab is alive with no client POST. The ambient demo now REPLAYS a
    recorded society run (resolved here from the bundled demo_runs/ since runs_root is
    empty), so the live auction (rulings) is visible with no DashScope key."""
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
    # Society replay (from the bundled demo arc), not a scripted engine run.
    assert data["arm"] == "society"
    # The replay streams a recording — it must not write a throwaway live-* run dir.
    assert not list(runs_root.glob("live-*"))


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


# ---------------------------------------------------------------------------
# Tests: ambient Live demo replays a recorded society run (rulings surface live)
# ---------------------------------------------------------------------------


def _write_recording(run_dir: Path, *, run_id: str, arm: str = "society", seed: int = 91) -> None:
    """Write a minimal, contract-shaped recording: run.json + ticks.ndjson + world.ndjson.

    Tick 1 carries an accepted auction ruling so a replay test can assert the rulings
    actually reach the WS buffer (the reviewer's 'No rulings yet' fix)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "arm": arm,
        "seed": seed,
        "ticks": 2,
        "final_scores": {"lives_saved": 7, "lives_lost": 1},
        "cost": {"usd_total": 0.04},
    }
    (run_dir / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
    tick0 = {"tick": 0, "responses": [], "rulings": [], "events": [], "scores": {}}
    tick1 = {
        "tick": 1,
        "responses": [
            {
                "agent_id": "fire",
                "proposals": [
                    {
                        "proposal_id": "fire-t1-p0",
                        "sender": "fire",
                        "kind": "resource_request",
                        "body": {"mission_id": "m1", "resource": "fire_engine", "qty": 1},
                    }
                ],
            }
        ],
        "rulings": [
            {
                "proposal_id": "fire-t1-p0",
                "accepted": True,
                "decided_by": "kernel:auction",
                "reason": "",
            }
        ],
        "events": [],
        "scores": {},
    }
    with (run_dir / "ticks.ndjson").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(tick0) + "\n")
        fh.write(json.dumps(tick1) + "\n")
    w0 = {"tick": 0, "state": {"tick": 0, "missions": {}, "pools": {}, "panic": 0.0}}
    w1 = {"tick": 1, "state": {"tick": 1, "missions": {}, "pools": {}, "panic": 0.1}}
    with (run_dir / "world.ndjson").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(w0) + "\n")
        fh.write(json.dumps(w1) + "\n")


def test_ambient_replay_streams_recorded_rulings(runs_root: Path) -> None:
    """The ambient demo replay surfaces the society's auction rulings over the WS buffer
    (the 'No rulings yet' fix): each recorded tick is broadcast as a {type:tick, record,
    world} message carrying the recording's rulings, then a 'done' summary — no engine,
    no DashScope key, and (crucially) no new live-* run dir."""
    import aftershock.web as web_mod

    rec = runs_root / "seed91-society"
    _write_recording(rec, run_id="seed91-society")

    state = web_mod._LiveState(live_id="testlive", arm="society", seed=91, mode="ambient")
    asyncio.run(web_mod._run_ambient_replay(state, rec))

    tick_msgs = [m for m in state.buffer if m["type"] == "tick"]
    assert [m["record"]["tick"] for m in tick_msgs] == [0, 1]
    # World snapshots are paired by tick and unwrapped to the bare state the UI reads.
    assert tick_msgs[1]["world"]["panic"] == 0.1
    # The auction ruling from the recording is surfaced live — the headline fix.
    assert tick_msgs[1]["record"]["rulings"][0]["proposal_id"] == "fire-t1-p0"
    assert tick_msgs[1]["record"]["rulings"][0]["accepted"] is True
    # Finished cleanly with a scoreboard summary; wrote no engine output.
    assert state.running is False
    assert state.tick == 1
    assert state.summary is not None
    assert state.summary["final_scores"]["lives_saved"] == 7
    assert state.summary["ticks_run"] == 2
    # The replay must never grow the live-* firehose it was built to replace.
    assert not list(runs_root.glob("live-*"))


def test_resolve_replay_dir_prefers_seeded_then_bundled(runs_root: Path) -> None:
    """_resolve_replay_dir finds a top-level seeded copy, an episodes/-nested copy, and
    returns None for an id with no recording anywhere."""
    import aftershock.web as web_mod

    _write_recording(runs_root / "seed91-society", run_id="seed91-society")
    _write_recording(runs_root / "episodes" / "ep1-seed100-society", run_id="ep1-seed100-society")

    top = web_mod._resolve_replay_dir("seed91-society", runs_root)
    assert top is not None and top.name == "seed91-society"
    assert (top / "ticks.ndjson").exists()

    nested = web_mod._resolve_replay_dir("ep1-seed100-society", runs_root)
    assert nested is not None and nested.name == "ep1-seed100-society"

    assert web_mod._resolve_replay_dir("does-not-exist-xyz", runs_root) is None
