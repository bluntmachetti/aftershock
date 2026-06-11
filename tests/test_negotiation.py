"""Tests for the Resolver Protocol and DefaultResolver."""

from __future__ import annotations

import random

import pytest

from aftershock.kernel.negotiation import DefaultResolver
from aftershock.kernel.protocol import (
    Proposal,
    ProposalKind,
    ProposalResponse,
)


def _prop(pid: str, sender: str = "a", recipient: str | None = None) -> Proposal:
    return Proposal(
        proposal_id=pid,
        sender=sender,
        recipient=recipient,
        kind=ProposalKind.RESOURCE_REQUEST,
    )


def _resp(pid: str, responder: str, accept: bool, note: str = "") -> ProposalResponse:
    return ProposalResponse(proposal_id=pid, responder=responder, accept=accept, note=note)


@pytest.fixture()
def resolver() -> DefaultResolver:
    return DefaultResolver()


@pytest.fixture()
def rng() -> random.Random:
    return random.Random(0)


# ---------------------------------------------------------------------------
# DefaultResolver — answered
# ---------------------------------------------------------------------------


def test_answered_accept(resolver: DefaultResolver, rng: random.Random) -> None:
    prop = _prop("p1", sender="alice")
    resp = _resp("p1", responder="bob", accept=True, note="sure")
    rulings, decisions = resolver.resolve({}, 0, [], [(prop, resp)], [], rng)
    assert len(rulings) == 1
    assert rulings[0].proposal_id == "p1"
    assert rulings[0].accepted is True
    assert rulings[0].decided_by == "bob"
    assert rulings[0].reason == "sure"
    assert decisions == []


def test_answered_decline(resolver: DefaultResolver, rng: random.Random) -> None:
    prop = _prop("p2", sender="alice")
    resp = _resp("p2", responder="bob", accept=False, note="no capacity")
    rulings, _ = resolver.resolve({}, 0, [], [(prop, resp)], [], rng)
    assert rulings[0].accepted is False
    assert rulings[0].decided_by == "bob"
    assert rulings[0].reason == "no capacity"


# ---------------------------------------------------------------------------
# DefaultResolver — expired
# ---------------------------------------------------------------------------


def test_expired(resolver: DefaultResolver, rng: random.Random) -> None:
    prop = _prop("p3")
    rulings, decisions = resolver.resolve({}, 1, [], [], [prop], rng)
    assert len(rulings) == 1
    assert rulings[0].proposal_id == "p3"
    assert rulings[0].accepted is False
    assert rulings[0].decided_by == "kernel:timeout"
    assert rulings[0].reason == "no response"
    assert decisions == []


# ---------------------------------------------------------------------------
# DefaultResolver — arbiter
# ---------------------------------------------------------------------------


def test_arbiter_declined(resolver: DefaultResolver, rng: random.Random) -> None:
    prop = _prop("p4")
    rulings, decisions = resolver.resolve({}, 2, [prop], [], [], rng)
    assert len(rulings) == 1
    assert rulings[0].proposal_id == "p4"
    assert rulings[0].accepted is False
    assert rulings[0].decided_by == "kernel:default"
    assert rulings[0].reason == "no arbiter configured"
    assert decisions == []


def test_multiple_categories(resolver: DefaultResolver, rng: random.Random) -> None:
    arb = _prop("arb1")
    ans_prop = _prop("ans1")
    ans_resp = _resp("ans1", responder="x", accept=True)
    exp = _prop("exp1")

    rulings, _ = resolver.resolve({}, 3, [arb], [(ans_prop, ans_resp)], [exp], rng)
    ids = {r.proposal_id for r in rulings}
    assert ids == {"arb1", "ans1", "exp1"}

    by_id = {r.proposal_id: r for r in rulings}
    assert by_id["arb1"].decided_by == "kernel:default"
    assert by_id["ans1"].decided_by == "x"
    assert by_id["exp1"].decided_by == "kernel:timeout"


def test_no_proposals_returns_empty(resolver: DefaultResolver, rng: random.Random) -> None:
    rulings, decisions = resolver.resolve({}, 0, [], [], [], rng)
    assert rulings == []
    assert decisions == []
