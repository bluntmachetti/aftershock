"""Agent ABC and ScriptedAgent convenience base.

Agents communicate exclusively through Observation / AgentResponse.
Scripted agents must be pure functions of the observation (deterministic,
stable tie-breaking).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from aftershock.kernel.protocol import AgentResponse, Observation


class Agent(ABC):
    def __init__(self, agent_id: str, role: str) -> None:
        self.agent_id = agent_id
        self.role = role

    @abstractmethod
    async def act(self, observation: Observation) -> AgentResponse:
        """Produce decisions, proposals, and responses for this tick."""


class ScriptedAgent(Agent):
    """Convenience base for synchronous scripted agents.

    Subclass implements ``act_sync(observation) -> AgentResponse``; this base
    wraps it in a coroutine so scripted and LLM agents are interchangeable.
    """

    @abstractmethod
    def act_sync(self, observation: Observation) -> AgentResponse:
        """Pure, deterministic function of the observation."""

    async def act(self, observation: Observation) -> AgentResponse:
        return await asyncio.get_event_loop().run_in_executor(None, self.act_sync, observation)
