"""Tests for CLI arms: society arm, smoke-llm, scripted arm, timeout flag."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# The aftershock binary lives next to the Python interpreter in the venv
_AFTERSHOCK_BIN = str(Path(sys.executable).parent / "aftershock")


def _run_aftershock(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Run the aftershock CLI as a subprocess using the venv binary."""
    cmd_env = env if env is not None else dict(os.environ)
    return subprocess.run(
        [_AFTERSHOCK_BIN, *args],
        capture_output=True,
        text=True,
        env=cmd_env,
    )


def _env_without_key() -> dict[str, str]:
    """Return os.environ with DASHSCOPE_API_KEY removed."""
    e = dict(os.environ)
    e.pop("DASHSCOPE_API_KEY", None)
    return e


def _assert_rc(result: subprocess.CompletedProcess[str], expected: int) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode == expected, (
        f"Expected exit {expected}, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    _ = combined  # silence unused-variable


# ---------------------------------------------------------------------------
# society arm without key -> exit 2 + friendly hint
# ---------------------------------------------------------------------------


def test_society_arm_without_key_exits_2() -> None:
    """--arm society without DASHSCOPE_API_KEY must exit 2."""
    result = _run_aftershock(
        "run", "--seed", "1", "--ticks", "5", "--arm", "society",
        env=_env_without_key(),
    )
    _assert_rc(result, 2)


def test_society_arm_without_key_prints_hint() -> None:
    """--arm society without DASHSCOPE_API_KEY must print a friendly two-line hint."""
    result = _run_aftershock(
        "run", "--seed", "1", "--ticks", "5", "--arm", "society",
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert "DASHSCOPE_API_KEY" in combined, (
        f"Expected hint mentioning DASHSCOPE_API_KEY in output:\n{combined}"
    )
    nonempty_lines = [line for line in combined.splitlines() if line.strip()]
    assert len(nonempty_lines) >= 2, (
        f"Expected at least 2 hint lines, got:\n{combined}"
    )


def test_society_arm_without_key_no_run_dir_created() -> None:
    """--arm society without key must exit before creating any run directory."""
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "1", "--ticks", "5", "--arm", "society", "--out", td,
            env=_env_without_key(),
        )
        _assert_rc(result, 2)
        created = os.listdir(td)
        assert created == [], f"No run dir should be created, found: {created}"


# ---------------------------------------------------------------------------
# smoke-llm without key -> exit 2
# ---------------------------------------------------------------------------


def test_smoke_llm_without_key_exits_2() -> None:
    """smoke-llm without DASHSCOPE_API_KEY must exit 2."""
    result = _run_aftershock("smoke-llm", env=_env_without_key())
    _assert_rc(result, 2)


def test_smoke_llm_without_key_prints_hint() -> None:
    """smoke-llm without key must print a friendly hint."""
    result = _run_aftershock("smoke-llm", env=_env_without_key())
    combined = result.stdout + result.stderr
    assert "DASHSCOPE_API_KEY" in combined, (
        f"Expected hint in output:\n{combined}"
    )


# ---------------------------------------------------------------------------
# scripted arm still works
# ---------------------------------------------------------------------------


def test_scripted_arm_runs_successfully() -> None:
    """--arm scripted must complete without error."""
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "42", "--ticks", "10", "--arm", "scripted",
            "--out", td, "--quiet",
            env=_env_without_key(),
        )
        _assert_rc(result, 0)


def test_scripted_arm_default_works() -> None:
    """Default arm (scripted) runs without specifying --arm."""
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "7", "--ticks", "5",
            "--out", td, "--quiet",
            env=_env_without_key(),
        )
        _assert_rc(result, 0)


# ---------------------------------------------------------------------------
# --timeout flag accepted
# ---------------------------------------------------------------------------


def test_timeout_flag_accepted_for_scripted() -> None:
    """--timeout flag must be accepted for scripted arm."""
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "run", "--seed", "1", "--ticks", "5", "--arm", "scripted",
            "--timeout", "10.0", "--out", td, "--quiet",
            env=_env_without_key(),
        )
        _assert_rc(result, 0)


def test_timeout_flag_accepted_society_without_key_still_exits_2() -> None:
    """--timeout does not bypass the key check for society arm."""
    result = _run_aftershock(
        "run", "--seed", "1", "--ticks", "5", "--arm", "society",
        "--timeout", "60.0",
        env=_env_without_key(),
    )
    _assert_rc(result, 2)


# ---------------------------------------------------------------------------
# swarm arm without key -> exit 2 + friendly hint
# ---------------------------------------------------------------------------


def test_swarm_arm_without_key_exits_2() -> None:
    """--arm swarm without DASHSCOPE_API_KEY must exit 2."""
    result = _run_aftershock(
        "run", "--seed", "1", "--ticks", "5", "--arm", "swarm",
        env=_env_without_key(),
    )
    _assert_rc(result, 2)


def test_swarm_arm_without_key_prints_hint() -> None:
    """--arm swarm without key must print a friendly hint mentioning DASHSCOPE_API_KEY."""
    result = _run_aftershock(
        "run", "--seed", "1", "--ticks", "5", "--arm", "swarm",
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert "DASHSCOPE_API_KEY" in combined, (
        f"Expected hint mentioning DASHSCOPE_API_KEY:\n{combined}"
    )
    nonempty_lines = [line for line in combined.splitlines() if line.strip()]
    assert len(nonempty_lines) >= 2, (
        f"Expected at least 2 hint lines, got:\n{combined}"
    )


# ---------------------------------------------------------------------------
# solo arm without key -> exit 2 + friendly hint
# ---------------------------------------------------------------------------


def test_solo_arm_without_key_exits_2() -> None:
    """--arm solo without DASHSCOPE_API_KEY must exit 2."""
    result = _run_aftershock(
        "run", "--seed", "1", "--ticks", "5", "--arm", "solo",
        env=_env_without_key(),
    )
    _assert_rc(result, 2)


def test_solo_arm_without_key_prints_hint() -> None:
    """--arm solo without key must print a friendly hint mentioning DASHSCOPE_API_KEY."""
    result = _run_aftershock(
        "run", "--seed", "1", "--ticks", "5", "--arm", "solo",
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert "DASHSCOPE_API_KEY" in combined, (
        f"Expected hint mentioning DASHSCOPE_API_KEY:\n{combined}"
    )
    nonempty_lines = [line for line in combined.splitlines() if line.strip()]
    assert len(nonempty_lines) >= 2, (
        f"Expected at least 2 hint lines, got:\n{combined}"
    )


# ---------------------------------------------------------------------------
# bench: keyless with LLM arms -> exit 2 before any cell
# ---------------------------------------------------------------------------


def test_bench_llm_arm_without_key_exits_2() -> None:
    """bench with an LLM arm and no DASHSCOPE_API_KEY must exit 2."""
    result = _run_aftershock(
        "bench", "--arms", "society", "--seeds", "42", "--ticks", "5",
        env=_env_without_key(),
    )
    _assert_rc(result, 2)


def test_bench_llm_arm_without_key_prints_hint() -> None:
    """bench with an LLM arm and no key must print a friendly hint."""
    result = _run_aftershock(
        "bench", "--arms", "society", "--seeds", "42", "--ticks", "5",
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert "DASHSCOPE_API_KEY" in combined, (
        f"Expected hint mentioning DASHSCOPE_API_KEY:\n{combined}"
    )


def test_bench_llm_arm_without_key_no_cell_dirs_created() -> None:
    """bench with an LLM arm and no key must exit before creating any cell dirs."""
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "bench", "--arms", "society", "--seeds", "42", "--ticks", "5",
            "--out", td,
            env=_env_without_key(),
        )
        _assert_rc(result, 2)
        created = [p for p in os.listdir(td) if not p.startswith(".")]
        assert created == [], f"No cell dirs should be created, found: {created}"


def test_bench_swarm_arm_without_key_exits_2() -> None:
    """bench with swarm arm and no key must exit 2."""
    result = _run_aftershock(
        "bench", "--arms", "swarm", "--seeds", "42", "--ticks", "5",
        env=_env_without_key(),
    )
    _assert_rc(result, 2)


# ---------------------------------------------------------------------------
# bench --arms scripted --seeds 42,7 --ticks 8: end-to-end offline
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# bench --seeds with invalid value -> exit 1 + friendly error
# ---------------------------------------------------------------------------


def test_bench_invalid_seeds_exits_1() -> None:
    """bench --seeds with a non-integer value must exit 1 with a friendly error."""
    result = _run_aftershock(
        "bench", "--arms", "scripted", "--seeds", "42,abc", "--ticks", "5",
        env=_env_without_key(),
    )
    _assert_rc(result, 1)


def test_bench_invalid_seeds_prints_error_message() -> None:
    """bench --seeds with invalid value must print a clear error, not a traceback."""
    result = _run_aftershock(
        "bench", "--arms", "scripted", "--seeds", "42,abc", "--ticks", "5",
        env=_env_without_key(),
    )
    combined = result.stdout + result.stderr
    assert "error" in combined.lower(), (
        f"Expected an error message, got:\n{combined}"
    )
    assert "Traceback" not in combined, (
        f"Should not print a raw traceback, got:\n{combined}"
    )
    assert "--seeds" in combined, (
        f"Error message should mention --seeds, got:\n{combined}"
    )


# ---------------------------------------------------------------------------
# bench --arms scripted --seeds 42,7 --ticks 8: end-to-end offline
# ---------------------------------------------------------------------------


def test_bench_scripted_two_seeds_end_to_end() -> None:
    """bench --arms scripted --seeds 42,7 --ticks 8 runs offline, writes RESULTS.md + results.json
    and the printed table contains both seeds."""
    with tempfile.TemporaryDirectory() as td:
        result = _run_aftershock(
            "bench",
            "--arms", "scripted",
            "--seeds", "42,7",
            "--ticks", "8",
            "--out", td,
            env=_env_without_key(),
        )
        _assert_rc(result, 0)

        # RESULTS.md must exist and contain both seeds
        results_md = Path(td) / "RESULTS.md"
        assert results_md.exists(), "RESULTS.md was not written"
        md_text = results_md.read_text(encoding="utf-8")
        assert "42" in md_text, "Seed 42 missing from RESULTS.md"
        assert "7" in md_text, "Seed 7 missing from RESULTS.md"

        # results.json must exist and be valid JSON
        results_json = Path(td) / "results.json"
        assert results_json.exists(), "results.json was not written"
        import json
        data = json.loads(results_json.read_text(encoding="utf-8"))
        assert "arms" in data
        assert "scripted" in data["arms"]

        # stdout table must also mention both seeds
        combined = result.stdout + result.stderr
        assert "scripted" in combined, "arm 'scripted' missing from stdout table"
        assert "42" in combined, "seed 42 missing from stdout table"
        assert "7" in combined, "seed 7 missing from stdout table"


# ---------------------------------------------------------------------------
# serve / mcp subcommands appear in --help
# ---------------------------------------------------------------------------


def test_serve_in_top_level_help() -> None:
    """'serve' must appear in the top-level --help output."""
    result = _run_aftershock("--help")
    assert "serve" in result.stdout + result.stderr, (
        f"'serve' not found in help:\n{result.stdout}{result.stderr}"
    )


def test_mcp_in_top_level_help() -> None:
    """'mcp' must appear in the top-level --help output."""
    result = _run_aftershock("--help")
    assert "mcp" in result.stdout + result.stderr, (
        f"'mcp' not found in help:\n{result.stdout}{result.stderr}"
    )


def test_serve_help_exits_0() -> None:
    """aftershock serve --help must exit 0."""
    result = _run_aftershock("serve", "--help")
    _assert_rc(result, 0)


def test_serve_help_shows_runs_dir() -> None:
    """aftershock serve --help must mention --runs-dir."""
    result = _run_aftershock("serve", "--help")
    combined = result.stdout + result.stderr
    assert "--runs-dir" in combined, f"'--runs-dir' not in serve help:\n{combined}"


def test_serve_help_shows_host_and_port() -> None:
    """aftershock serve --help must mention --host and --port."""
    result = _run_aftershock("serve", "--help")
    combined = result.stdout + result.stderr
    assert "--host" in combined, f"'--host' not in serve help:\n{combined}"
    assert "--port" in combined, f"'--port' not in serve help:\n{combined}"


def test_mcp_help_exits_0() -> None:
    """aftershock mcp --help must exit 0."""
    result = _run_aftershock("mcp", "--help")
    _assert_rc(result, 0)


def test_mcp_help_shows_runs_dir() -> None:
    """aftershock mcp --help must mention --runs-dir."""
    result = _run_aftershock("mcp", "--help")
    combined = result.stdout + result.stderr
    assert "--runs-dir" in combined, f"'--runs-dir' not in mcp help:\n{combined}"


# ---------------------------------------------------------------------------
# create_app importable from cli wiring
# ---------------------------------------------------------------------------


def test_create_app_importable_from_web() -> None:
    """create_app must be importable from aftershock.web (the module cli wires serve to)."""
    from aftershock.web import create_app  # noqa: F401 — just assert it imports

    assert callable(create_app)


def test_create_app_returns_fastapi_app() -> None:
    """create_app() must return a FastAPI application instance."""
    import tempfile
    from pathlib import Path

    from fastapi import FastAPI

    from aftershock.web import create_app

    with tempfile.TemporaryDirectory() as td:
        app = create_app(runs_root=Path(td))
    assert isinstance(app, FastAPI)
