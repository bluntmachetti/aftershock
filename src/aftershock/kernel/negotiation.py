"""Resolver Protocol and DefaultResolver.

The Resolver is the extension point for contested-resource arbitration.
The engine handles routing; the resolver only needs to produce rulings and
optional granted decisions for the proposals it receives.
"""

from __future__ import annotations

import random
from typing import Any, Protocol, runtime_checkable

from aftershock.kernel.protocol import Decision, Proposal, ProposalResponse, ProposalRuling


@runtime_checkable
class Resolver(Protocol):
    name: str

    def resolve(
        self,
        world: Any,
        tick: int,
        arbiter: list[Proposal],
        answered: list[tuple[Proposal, ProposalResponse]],
        expired: list[Proposal],
        rng: random.Random,
    ) -> tuple[list[ProposalRuling], list[Decision]]:
        """Return rulings for every proposal handed to this resolver, plus any
        kernel-granted decisions (e.g. auction wins become dispatches).

        Every proposal in *arbiter*, *answered*, and *expired* must get a ruling.
        Granted decisions are validated against the full registry with
        ``allowed=None``; use ``decision_id = f"{proposal_id}-grant"``.
        """
        ...


class DefaultResolver:
    """Fall-through resolver with no arbitration capability.

    - answered  → ruling mirroring the responder's accept/decline
    - expired   → declined, decided_by="kernel:timeout", reason="no response"
    - arbiter   → declined, decided_by="kernel:default", reason="no arbiter configured"
    """

    name = "default"

    def resolve(
        self,
        world: Any,  # noqa: ARG002
        tick: int,  # noqa: ARG002
        arbiter: list[Proposal],
        answered: list[tuple[Proposal, ProposalResponse]],
        expired: list[Proposal],
        rng: random.Random,  # noqa: ARG002
    ) -> tuple[list[ProposalRuling], list[Decision]]:
        rulings: list[ProposalRuling] = []

        for proposal, response in answered:
            rulings.append(
                ProposalRuling(
                    proposal_id=proposal.proposal_id,
                    accepted=response.accept,
                    decided_by=response.responder,
                    reason=response.note,
                )
            )

        for proposal in expired:
            rulings.append(
                ProposalRuling(
                    proposal_id=proposal.proposal_id,
                    accepted=False,
                    decided_by="kernel:timeout",
                    reason="no response",
                )
            )

        for proposal in arbiter:
            rulings.append(
                ProposalRuling(
                    proposal_id=proposal.proposal_id,
                    accepted=False,
                    decided_by="kernel:default",
                    reason="no arbiter configured",
                )
            )

        return rulings, []
