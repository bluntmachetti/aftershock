"""The single chokepoint for all model calls: QwenProvider + MockProvider.

Every LLM call in the project goes through Provider.chat so cost accounting,
retries, and request shaping live in exactly one place.
"""

from __future__ import annotations

import asyncio
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


@dataclass(frozen=True)
class ChatResult:
    text: str
    usage: TokenUsage  # cost_usd computed from MODEL_PRICES (unknown model -> 0.0)


class Provider(Protocol):
    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float,
        json_mode: bool = True,
    ) -> ChatResult: ...


class ProviderError(Exception):
    """Raised when a provider call fails unrecoverably."""


class QwenProvider:
    """Calls DashScope-compatible /chat/completions with retry/backoff."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DASHSCOPE_INTL_BASE,
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
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._transport = transport

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
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if json_mode:
            # DashScope JSON-mode rules: response_format + disable thinking; never max_tokens
            body["response_format"] = {"type": "json_object"}
            body["enable_thinking"] = False

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
                    raise ProviderError(
                        f"Unexpected HTTP {resp.status_code}: {resp.text[:200]}"
                    )

                data = resp.json()
                text: str = data["choices"][0]["message"]["content"]
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
                return ChatResult(text=text, usage=usage)

        raise ProviderError(
            f"All {self._max_retries + 1} attempts failed. Last error: {last_error}"
        )


class MockProvider:
    """Scripted provider for offline tests. Records every call in .calls."""

    def __init__(self, script: list[str] | Callable[[str, str, str], str]) -> None:
        self._script = script
        self._index = 0
        self.calls: list[tuple[str, str, str]] = []

    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        temperature: float,  # noqa: ARG002
        json_mode: bool = True,  # noqa: ARG002
    ) -> ChatResult:
        self.calls.append((model, system, user))

        if callable(self._script):
            text = self._script(model, system, user)
        else:
            if self._index >= len(self._script):
                raise ProviderError("MockProvider script exhausted")
            text = self._script[self._index]
            self._index += 1

        # Fabricate plausible token counts: len//4 each for prompt and completion
        prompt_tokens = len(system) // 4
        completion_tokens = len(text) // 4
        cost = _compute_cost(model, prompt_tokens, completion_tokens)
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            model=model,
        )
        return ChatResult(text=text, usage=usage)
