"""Tests for DecisionHandler ABC and DecisionRegistry.

Uses small inline toy handlers with a plain dict as the world.
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from pydantic import BaseModel

from aftershock.kernel.protocol import Decision, WorldEvent
from aftershock.kernel.registry import DecisionHandler, DecisionRegistry

# ---------------------------------------------------------------------------
# Toy domain models
# ---------------------------------------------------------------------------


class AddParams(BaseModel):
    key: str
    value: int


class AddHandler(DecisionHandler):
    decision_type = "add"
    Params = AddParams

    def validate(self, world: Any, params: BaseModel) -> str | None:
        assert isinstance(params, AddParams)
        if params.key in world:
            return f"key {params.key!r} already exists"
        return None

    def apply(
        self,
        world: Any,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        assert isinstance(params, AddParams)
        world[params.key] = params.value
        return [
            WorldEvent(
                event_id=f"add-{tick}",
                tick=tick,
                kind="added",
                payload={"key": params.key, "value": params.value},
            )
        ]


class BananaParams(BaseModel):
    count: int


class BananaHandler(DecisionHandler):
    decision_type = "banana"
    Params = BananaParams

    def validate(self, world: Any, params: BaseModel) -> str | None:
        assert isinstance(params, BananaParams)
        if params.count > 100:
            return "too many bananas"
        return None

    def apply(
        self,
        world: Any,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        assert isinstance(params, BananaParams)
        return [
            WorldEvent(
                event_id=f"banana-{tick}",
                tick=tick,
                kind="banana_added",
                payload={"count": params.count},
            )
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_decision(
    decision_type: str,
    params: dict,
    *,
    decision_id: str = "d-0",
    agent_id: str = "agent",
) -> Decision:
    return Decision(
        decision_id=decision_id,
        agent_id=agent_id,
        decision_type=decision_type,
        params=params,
    )


def make_registry(*handlers: DecisionHandler) -> DecisionRegistry:
    reg = DecisionRegistry()
    for h in handlers:
        reg.register(h)
    return reg


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_duplicate_raises() -> None:
    reg = DecisionRegistry()
    reg.register(AddHandler())
    with pytest.raises(ValueError, match="duplicate decision_type"):
        reg.register(AddHandler())


def test_decision_types_sorted() -> None:
    reg = make_registry(BananaHandler(), AddHandler())
    assert reg.decision_types() == ("add", "banana")


# ---------------------------------------------------------------------------
# Validation rejection paths — each produces a distinct human-readable reason
# ---------------------------------------------------------------------------


def test_unknown_type_rejection() -> None:
    reg = make_registry(AddHandler())
    d = make_decision("nonexistent", {})
    params, reason = reg.validate({}, d, allowed=None)
    assert params is None
    assert reason is not None
    assert "unknown decision type" in reason
    assert "nonexistent" in reason


def test_envelope_rejection() -> None:
    reg = make_registry(AddHandler(), BananaHandler())
    d = make_decision("banana", {"count": 5})
    # Only "add" is allowed
    params, reason = reg.validate({}, d, allowed=("add",))
    assert params is None
    assert reason is not None
    assert "not in role envelope" in reason
    assert "banana" in reason


def test_params_parse_rejection() -> None:
    reg = make_registry(AddHandler())
    # "value" should be int; pass a non-coercible string
    d = make_decision("add", {"key": "x", "value": "not-an-int"})
    params, reason = reg.validate({}, d, allowed=None)
    assert params is None
    assert reason is not None
    assert "invalid params" in reason
    # pydantic error message should mention the field
    assert "value" in reason


def test_handler_validate_rejection() -> None:
    reg = make_registry(AddHandler())
    world: dict = {"x": 1}
    d = make_decision("add", {"key": "x", "value": 99})
    params, reason = reg.validate(world, d, allowed=None)
    assert params is None
    assert reason is not None
    assert "already exists" in reason


def test_missing_required_param_rejection() -> None:
    reg = make_registry(AddHandler())
    # Missing required "value" field
    d = make_decision("add", {"key": "x"})
    params, reason = reg.validate({}, d, allowed=None)
    assert params is None
    assert reason is not None
    assert "invalid params" in reason


def test_too_many_bananas_rejection() -> None:
    reg = make_registry(BananaHandler())
    d = make_decision("banana", {"count": 999})
    params, reason = reg.validate({}, d, allowed=None)
    assert params is None
    assert reason is not None
    assert "too many bananas" in reason


# ---------------------------------------------------------------------------
# Successful validation and apply
# ---------------------------------------------------------------------------


def test_validate_success() -> None:
    reg = make_registry(AddHandler())
    d = make_decision("add", {"key": "new_key", "value": 42})
    params, reason = reg.validate({}, d, allowed=None)
    assert reason is None
    assert params is not None
    assert isinstance(params, AddParams)
    assert params.key == "new_key"
    assert params.value == 42


def test_validate_success_with_envelope() -> None:
    reg = make_registry(AddHandler(), BananaHandler())
    d = make_decision("add", {"key": "k", "value": 1})
    params, reason = reg.validate({}, d, allowed=("add", "banana"))
    assert reason is None
    assert params is not None


def test_allowed_none_means_any() -> None:
    reg = make_registry(BananaHandler())
    d = make_decision("banana", {"count": 5})
    params, reason = reg.validate({}, d, allowed=None)
    assert reason is None
    assert params is not None


def test_apply_returns_world_events() -> None:
    reg = make_registry(AddHandler())
    world: dict = {}
    d = make_decision("add", {"key": "hello", "value": 7})
    params, reason = reg.validate(world, d, allowed=None)
    assert reason is None
    assert params is not None

    rng = random.Random(0)
    events = reg.apply(world, d, params, tick=3, rng=rng)

    assert world == {"hello": 7}
    assert len(events) == 1
    assert events[0].kind == "added"
    assert events[0].tick == 3
    assert events[0].payload == {"key": "hello", "value": 7}


def test_apply_banana_returns_world_events() -> None:
    reg = make_registry(BananaHandler())
    d = make_decision("banana", {"count": 10})
    params, reason = reg.validate({}, d, allowed=None)
    assert reason is None
    assert params is not None

    rng = random.Random(0)
    events = reg.apply({}, d, params, tick=1, rng=rng)

    assert len(events) == 1
    assert events[0].kind == "banana_added"
    assert events[0].payload["count"] == 10


# ---------------------------------------------------------------------------
# Envelope edge cases
# ---------------------------------------------------------------------------


def test_empty_envelope_rejects_everything() -> None:
    reg = make_registry(AddHandler())
    d = make_decision("add", {"key": "x", "value": 1})
    params, reason = reg.validate({}, d, allowed=())
    assert params is None
    assert reason is not None
    assert "not in role envelope" in reason


def test_envelope_rejection_reason_lists_envelope() -> None:
    reg = make_registry(AddHandler(), BananaHandler())
    d = make_decision("banana", {"count": 1})
    params, reason = reg.validate({}, d, allowed=("add",))
    assert reason is not None
    # The envelope listing should appear in the reason
    assert "add" in reason
