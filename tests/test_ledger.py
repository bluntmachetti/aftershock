"""Tests for ledger.py: aggregation across agents and models."""

import pytest

from aftershock.kernel.ledger import CostLedger
from aftershock.kernel.protocol import TokenUsage


def _usage(prompt: int, completion: int, cost: float, model: str = "m1") -> TokenUsage:
    return TokenUsage(
        prompt_tokens=prompt, completion_tokens=completion, cost_usd=cost, model=model
    )


def test_totals_empty():
    ledger = CostLedger()
    t = ledger.totals()
    assert t["prompt_tokens"] == 0
    assert t["completion_tokens"] == 0
    assert t["cost_usd"] == 0.0
    assert t["by_agent"] == {}
    assert t["by_model"] == {}


def test_single_record():
    ledger = CostLedger()
    ledger.record(0, "medical", _usage(100, 20, 0.01, "gpt-4"))
    t = ledger.totals()
    assert t["prompt_tokens"] == 100
    assert t["completion_tokens"] == 20
    assert t["cost_usd"] == pytest.approx(0.01)
    assert "medical" in t["by_agent"]
    assert t["by_agent"]["medical"]["prompt_tokens"] == 100
    assert "gpt-4" in t["by_model"]
    assert t["by_model"]["gpt-4"]["completion_tokens"] == 20


def test_aggregation_across_agents():
    ledger = CostLedger()
    ledger.record(0, "medical", _usage(100, 10, 0.01, "m1"))
    ledger.record(0, "rescue", _usage(200, 30, 0.02, "m1"))
    ledger.record(1, "medical", _usage(50, 5, 0.005, "m1"))
    t = ledger.totals()
    assert t["prompt_tokens"] == 350
    assert t["completion_tokens"] == 45
    assert t["cost_usd"] == pytest.approx(0.035)
    assert t["by_agent"]["medical"]["prompt_tokens"] == 150
    assert t["by_agent"]["medical"]["completion_tokens"] == 15
    assert t["by_agent"]["rescue"]["prompt_tokens"] == 200


def test_aggregation_across_models():
    ledger = CostLedger()
    ledger.record(0, "a1", _usage(100, 10, 0.01, "fast"))
    ledger.record(0, "a2", _usage(200, 20, 0.02, "slow"))
    ledger.record(1, "a1", _usage(50, 5, 0.005, "fast"))
    t = ledger.totals()
    assert t["by_model"]["fast"]["prompt_tokens"] == 150
    assert t["by_model"]["fast"]["cost_usd"] == pytest.approx(0.015)
    assert t["by_model"]["slow"]["prompt_tokens"] == 200


def test_no_model_field_skips_by_model():
    ledger = CostLedger()
    ledger.record(0, "scripted", TokenUsage(prompt_tokens=10, completion_tokens=5, cost_usd=0.0))
    t = ledger.totals()
    assert t["by_model"] == {}
    assert t["by_agent"]["scripted"]["prompt_tokens"] == 10


def test_by_agent_and_by_model_keys_sorted():
    ledger = CostLedger()
    ledger.record(0, "zebra", _usage(1, 1, 0.0, "z-model"))
    ledger.record(0, "alpha", _usage(1, 1, 0.0, "a-model"))
    t = ledger.totals()
    assert list(t["by_agent"].keys()) == sorted(t["by_agent"].keys())
    assert list(t["by_model"].keys()) == sorted(t["by_model"].keys())


def test_multi_tick_same_agent_accumulates():
    ledger = CostLedger()
    for tick in range(5):
        ledger.record(tick, "fire", _usage(10, 2, 0.001, "base"))
    t = ledger.totals()
    assert t["by_agent"]["fire"]["prompt_tokens"] == 50
    assert t["by_agent"]["fire"]["completion_tokens"] == 10
    assert t["by_agent"]["fire"]["cost_usd"] == pytest.approx(0.005)

