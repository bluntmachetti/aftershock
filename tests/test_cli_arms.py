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
