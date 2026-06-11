"""Decision type registry: validate/apply plugins.

DecisionHandler subclasses register themselves; the registry enforces a
strict validation pipeline before any handler touches the world.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from aftershock.kernel.protocol import Decision, WorldEvent


class DecisionHandler(ABC):
    decision_type: ClassVar[str]
    Params: ClassVar[type[BaseModel]]

    @abstractmethod
    def validate(self, world: Any, params: BaseModel) -> str | None:
        """Return a rejection reason, or None if the decision is valid."""

    @abstractmethod
    def apply(
        self,
        world: Any,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        """Apply the decision to the world and return resulting events."""


class DecisionRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, DecisionHandler] = {}

    def register(self, handler: DecisionHandler) -> None:
        """Register a handler. Raises ValueError on duplicate decision_type."""
        dt = handler.decision_type
        if dt in self._handlers:
            raise ValueError(f"duplicate decision_type: {dt!r}")
        self._handlers[dt] = handler

    def decision_types(self) -> tuple[str, ...]:
        """Return all registered decision types, sorted."""
        return tuple(sorted(self._handlers))

    def validate(
        self,
        world: Any,
        decision: Decision,
        allowed: tuple[str, ...] | None,
    ) -> tuple[BaseModel | None, str | None]:
        """Validate a decision through the four-step pipeline.

        Steps (in order):
          1. Known decision_type — must be registered.
          2. Envelope check — if allowed is not None, type must be in allowed.
          3. Params parse — pydantic errors become the rejection reason.
          4. handler.validate — domain-level check.

        Returns (params, None) on success, (None, reason) on rejection.
        """
        # Step 1: known type
        handler = self._handlers.get(decision.decision_type)
        if handler is None:
            return None, f"unknown decision type: {decision.decision_type!r}"

        # Step 2: envelope
        if allowed is not None and decision.decision_type not in allowed:
            return None, (
                f"decision type {decision.decision_type!r} not in role envelope "
                f"({', '.join(sorted(allowed)) or 'none'})"
            )

        # Step 3: params parse
        try:
            params = handler.Params.model_validate(decision.params)
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
                for e in exc.errors()
            )
            return None, f"invalid params: {errors}"

        # Step 4: handler validate
        reason = handler.validate(world, params)
        if reason is not None:
            return None, reason

        return params, None

    def apply(
        self,
        world: Any,
        decision: Decision,
        params: BaseModel,
        tick: int,
        rng: random.Random,
    ) -> list[WorldEvent]:
        """Apply a previously-validated decision; caller must have called validate first."""
        handler = self._handlers[decision.decision_type]
        return handler.apply(world, params, tick, rng)
