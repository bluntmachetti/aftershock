"""The single chokepoint for all model calls: QwenProvider + MockProvider.

Every LLM call in the project goes through Provider.chat so cost accounting,
retries, and request shaping live in exactly one place.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from aftershock.kernel.protocol import TokenUsage

DASHSCOPE_INTL_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# (usd_per_1M_input, usd_per_1M_output) — first price tier
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "qwen3.5-flash": (0.10, 0.40),
    "qwen3.5-plus": (0.40, 2.40),
    "qwen3-max": (1.20, 6.00),
    "qwen-flash": (0.05, 0.40),
    "qwen-plus": (0.40, 1.20),
    "qwen-max": (1.60, 6.40),
    "qwen-turbo": (0.05, 0.20),
}


def _compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute cost in USD given model and token counts. Unknown model -> 0.0."""
    prices = MODEL_PRICES_USD_PER_MTOK.get(model)
    if prices is None:
        return 0.0
    input_price, output_price = prices
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


def endpoint_label(base_url: str | None) -> str:
    """Map a provider base_url to a provenance endpoint label.

    Mirrors QwenProvider's own endpoint detection (``"dashscope" in base_url``):
    a DashScope-International cloud URL -> "dashscope-intl"; any other (local /
    self-hosted Ollama OpenAI-compatible) URL -> "ollama-k12". ``None`` means no
    provider was wired at all (an LLM-free scripted-only run) -> "scripted".
    """
    if base_url is None:
        return "scripted"
    return "dashscope-intl" if "dashscope" in base_url else "ollama-k12"


@dataclass(frozen=True)
class ChatResult:
    text: str
    usage: TokenUsage  # cost_usd computed from MODEL_PRICES (unknown model -> 0.0)
    tool_calls: list[dict] | None = None


class Provider(Protocol):
    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float,
        json_mode: bool = True,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        seed: int | None = None,
    ) -> ChatResult: ...


class ProviderError(Exception):
    """Raised when a provider call fails unrecoverably."""


class QwenProvider:
    """Calls DashScope-compatible /chat/completions with retry/backoff."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = 45.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        if not resolved_key:
            raise ProviderError(
                "No DashScope API key found. "
                "Set the DASHSCOPE_API_KEY environment variable or pass api_key=."
            )
        self._api_key = resolved_key
        # base_url precedence: explicit arg > DASHSCOPE_BASE_URL env > DashScope cloud.
        # The env hook lets the whole stack point at a local OpenAI-compatible endpoint
        # (e.g. a self-hosted Ollama at http://host:11434/v1) with no code change.
        self._base_url = (
            base_url or os.environ.get("DASHSCOPE_BASE_URL") or DASHSCOPE_INTL_BASE
        ).rstrip("/")
        # Cloud DashScope disables Qwen3 reasoning via `enable_thinking`; a self-hosted
        # Ollama OpenAI endpoint ignores that and instead honors `reasoning_effort`.
        # Detect the endpoint so the cloud request stays byte-identical.
        self._is_dashscope = "dashscope" in self._base_url
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._transport = transport

    @property
    def base_url(self) -> str:
        """The resolved endpoint base URL (read-only; for provenance labeling)."""
        return self._base_url

    def _make_client(self) -> httpx.AsyncClient:
        kwargs: dict[str, Any] = {
            "headers": {"Authorization": f"Bearer {self._api_key}"},
            "timeout": self._timeout_s,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float,
        json_mode: bool = True,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        seed: int | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        # M1: forward a deterministic sampling seed when one is supplied. The
        # OpenAI-compatible DashScope endpoint accepts a top-level `seed`; whether
        # it makes sampling reproducible is the open empirical question (verify
        # with two re-runs → byte-identical decision records). Harmless when
        # ignored, so it is sent in both JSON and tool modes.
        if seed is not None:
            body["seed"] = seed
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
            body["parallel_tool_calls"] = True
            body["enable_thinking"] = False
        elif json_mode:
            body["response_format"] = {"type": "json_object"}
            body["enable_thinking"] = False
        # Self-hosted Ollama endpoints disable Qwen3 thinking via reasoning_effort
        # (they ignore enable_thinking). Gated on the endpoint → cloud body unchanged.
        if not self._is_dashscope:
            body["reasoning_effort"] = "none"

        url = f"{self._base_url}/chat/completions"
        backoff_delays = [0.5, 1.0, 2.0]
        last_error: Exception | None = None

        async with self._make_client() as client:
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await client.post(url, json=body)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = exc
                    if attempt < self._max_retries:
                        await asyncio.sleep(backoff_delays[min(attempt, len(backoff_delays) - 1)])
                    continue

                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = ProviderError(
                        f"HTTP {resp.status_code} from provider (attempt {attempt + 1})"
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(backoff_delays[min(attempt, len(backoff_delays) - 1)])
                    continue

                if resp.status_code != 200:
                    raise ProviderError(f"Unexpected HTTP {resp.status_code}: {resp.text[:200]}")

                data = resp.json()
                message = data["choices"][0]["message"]
                tool_calls: list[dict] | None = message.get("tool_calls")
                text: str = "" if tool_calls else (message.get("content", "") or "")
                usage_data = data.get("usage", {})
                prompt_tokens: int = usage_data.get("prompt_tokens", 0)
                completion_tokens: int = usage_data.get("completion_tokens", 0)
                cost = _compute_cost(model, prompt_tokens, completion_tokens)
                usage = TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=cost,
                    model=model,
                )
                return ChatResult(text=text, usage=usage, tool_calls=tool_calls)

        raise ProviderError(
            f"All {self._max_retries + 1} attempts failed. Last error: {last_error}"
        )


class MockProvider:
    """Scripted provider for offline tests. Records every call in .calls."""

    def __init__(
        self, script: list[str | dict] | Callable[[str, str, str], str | dict]
    ) -> None:
        self._script = script
        self._index = 0
        self.calls: list[tuple[str, str, str]] = []
        # M1: seeds passed per call, parallel to .calls (kept separate so the
        # pinned (model, system, user) tuple shape stays unchanged for callers).
        self.seed_calls: list[int | None] = []

    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float,  # noqa: ARG002
        json_mode: bool = True,  # noqa: ARG002
        tools: list[dict] | None = None,  # noqa: ARG002
        tool_choice: str | None = None,  # noqa: ARG002
        seed: int | None = None,
    ) -> ChatResult:
        self.calls.append((model, system, user))
        self.seed_calls.append(seed)

        if callable(self._script):
            entry = self._script(model, system, user)
        else:
            if self._index >= len(self._script):
                raise ProviderError("MockProvider script exhausted")
            entry = self._script[self._index]
            self._index += 1

        if isinstance(entry, dict) and "tool_calls" in entry:
            tool_calls = entry["tool_calls"]
            text = ""
            prompt_tokens = len(system) // 4
            completion_tokens = (
                sum(len(json.dumps(tc)) for tc in tool_calls) // 4 if tool_calls else 1
            )
        else:
            text = str(entry) if isinstance(entry, str) else json.dumps(entry)
            tool_calls = None
            prompt_tokens = len(system) // 4
            completion_tokens = len(text) // 4
        cost = _compute_cost(model, prompt_tokens, completion_tokens)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            model=model,
        )
        return ChatResult(text=text, usage=usage, tool_calls=tool_calls)
