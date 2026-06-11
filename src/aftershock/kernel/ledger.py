"""Token and cost accounting per agent and model."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from aftershock.kernel.protocol import TokenUsage


class CostLedger:
    """Accumulates token usage and cost across all ticks."""

    def __init__(self) -> None:
        self._prompt: int = 0
        self._completion: int = 0
        self._cost: float = 0.0
        self._by_agent: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        )
        self._by_model: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        )

    def record(self, tick: int, agent_id: str, usage: TokenUsage) -> None:  # noqa: ARG002
        self._prompt += usage.prompt_tokens
        self._completion += usage.completion_tokens
        self._cost += usage.cost_usd

        a = self._by_agent[agent_id]
        a["prompt_tokens"] += usage.prompt_tokens
        a["completion_tokens"] += usage.completion_tokens
        a["cost_usd"] += usage.cost_usd

        if usage.model:
            m = self._by_model[usage.model]
            m["prompt_tokens"] += usage.prompt_tokens
            m["completion_tokens"] += usage.completion_tokens
            m["cost_usd"] += usage.cost_usd

    def totals(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self._prompt,
            "completion_tokens": self._completion,
            "cost_usd": self._cost,
            "by_agent": {k: dict(v) for k, v in sorted(self._by_agent.items())},
            "by_model": {k: dict(v) for k, v in sorted(self._by_model.items())},
        }
