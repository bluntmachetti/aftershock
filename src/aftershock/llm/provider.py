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
from pathlib import Path
from typing import Any, Protocol

import httpx

from aftershock.kernel.protocol import TokenUsage

DASHSCOPE_INTL_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# (usd_per_1M_input, usd_per_1M_output) — first price tier. These are the project's
# own production Qwen models; external validation models (OpenRouter/Featherless) are
# supplied separately via AFTERSHOCK_MODEL_PRICES (see _load_extra_prices) so this
# table stays the authoritative Qwen price of record.
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "qwen3.5-flash": (0.10, 0.40),
    "qwen3.5-plus": (0.40, 2.40),
    "qwen3-max": (1.20, 6.00),
    "qwen-flash": (0.05, 0.40),
    "qwen-plus": (0.40, 1.20),
    "qwen-max": (1.60, 6.40),
    "qwen-turbo": (0.05, 0.20),
}

# Endpoint classification from a base_url. Governs (a) which API key env var to read,
# (b) request-body shaping (Qwen-only params vs plain OpenAI-compatible), and (c) the
# provenance label. "ollama" is the catch-all for a self-hosted OpenAI-compatible
# endpoint (Ollama/vLLM), distinct from the managed aggregators OpenRouter/Featherless.
_ENDPOINTS = ("dashscope", "openrouter", "featherless", "ollama")


def classify_endpoint(base_url: str) -> str:
    """Classify a base_url into one of _ENDPOINTS (default 'ollama' for self-hosted)."""
    u = base_url.lower()
    if "dashscope" in u:
        return "dashscope"
    if "openrouter" in u:
        return "openrouter"
    if "featherless" in u:
        return "featherless"
    return "ollama"


# Which env var holds the API key for each endpoint. OpenRouter/Featherless require
# their OWN key (no fall-back to the Qwen key — sending a DashScope key to OpenRouter
# would just 401). DashScope and self-hosted Ollama use DASHSCOPE_API_KEY (the latter
# is usually keyless; a dummy value satisfies the non-empty check).
_ENDPOINT_KEY_ENV: dict[str, str] = {
    "dashscope": "DASHSCOPE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "featherless": "FEATHERLESS_API_KEY",
    "ollama": "DASHSCOPE_API_KEY",
}


def _key_for_endpoint(endpoint: str) -> str:
    return os.environ.get(_ENDPOINT_KEY_ENV.get(endpoint, "DASHSCOPE_API_KEY"), "")


# Cache parsed AFTERSHOCK_MODEL_PRICES by its raw value so a file path isn't re-read
# on every cost computation. Keyed on the raw string → invalidates when the env changes.
_EXTRA_PRICE_CACHE: dict[str, dict[str, tuple[float, float]]] = {}


def _parse_extra_prices(raw: str) -> dict[str, tuple[float, float]]:
    """Parse AFTERSHOCK_MODEL_PRICES (inline JSON or a path to a JSON file).

    Shape: ``{"model-id": [usd_per_1M_input, usd_per_1M_output], ...}``. Any parse
    error yields {} (unknown models then cost $0.0 — honest, never a crash)."""
    try:
        raw_json = raw if raw.lstrip().startswith("{") else Path(raw).read_text()
        data = json.loads(raw_json)
        # Skip non-[in, out] entries (e.g. a "_comment" string) so a documented
        # price file doesn't blow the whole parse away.
        return {
            str(k): (float(v[0]), float(v[1]))
            for k, v in data.items()
            if isinstance(v, list | tuple) and len(v) == 2
        }
    except (OSError, ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
        return {}


def _load_extra_prices() -> dict[str, tuple[float, float]]:
    raw = os.environ.get("AFTERSHOCK_MODEL_PRICES", "").strip()
    if not raw:
        return {}
    if raw not in _EXTRA_PRICE_CACHE:
        _EXTRA_PRICE_CACHE[raw] = _parse_extra_prices(raw)
    return _EXTRA_PRICE_CACHE[raw]


def _price_for(model: str) -> tuple[float, float] | None:
    """Look up (in, out) price for a model — Qwen table first, then extra prices."""
    return MODEL_PRICES_USD_PER_MTOK.get(model) or _load_extra_prices().get(model)


def known_models() -> set[str]:
    """All models with a known price (Qwen table + AFTERSHOCK_MODEL_PRICES)."""
    return set(MODEL_PRICES_USD_PER_MTOK) | set(_load_extra_prices())


def _compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute cost in USD given model and token counts. Unknown model -> 0.0."""
    prices = _price_for(model)
    if prices is None:
        return 0.0
    input_price, output_price = prices
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


def endpoint_label(base_url: str | None) -> str:
    """Map a provider base_url to a provenance endpoint label.

    ``None`` means no provider was wired (an LLM-free scripted-only run) -> "scripted".
    DashScope cloud -> "dashscope-intl"; a self-hosted Ollama/vLLM -> "ollama-k12";
    the managed aggregators keep their own label so provenance never mislabels an
    OpenRouter/Featherless run as self-hosted."""
    if base_url is None:
        return "scripted"
    return {
        "dashscope": "dashscope-intl",
        "openrouter": "openrouter",
        "featherless": "featherless",
        "ollama": "ollama-k12",
    }[classify_endpoint(base_url)]


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
        # base_url precedence: explicit arg > DASHSCOPE_BASE_URL env > DashScope cloud.
        # The env hook lets the whole stack point at any OpenAI-compatible endpoint
        # (self-hosted Ollama, or the OpenRouter/Featherless aggregators) with no code
        # change — the model id and Bearer key pass straight through.
        self._base_url = (
            base_url or os.environ.get("DASHSCOPE_BASE_URL") or DASHSCOPE_INTL_BASE
        ).rstrip("/")
        # Endpoint governs body shaping (Qwen-only params stay off non-Qwen providers)
        # and which key env var to read. Cloud DashScope stays byte-identical.
        self._endpoint = classify_endpoint(self._base_url)
        self._is_dashscope = self._endpoint == "dashscope"
        # Key precedence: explicit arg > the endpoint's own key env var. OpenRouter and
        # Featherless require their own key so a Qwen key is never sent to the wrong host.
        resolved_key = api_key or _key_for_endpoint(self._endpoint)
        if not resolved_key:
            key_env = _ENDPOINT_KEY_ENV.get(self._endpoint, "DASHSCOPE_API_KEY")
            raise ProviderError(
                f"No API key found for the {self._endpoint} endpoint. "
                f"Set the {key_env} environment variable or pass api_key=."
            )
        self._api_key = resolved_key
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
        # enable_thinking is a Qwen/DashScope param (self-hosted Ollama ignores it,
        # OpenRouter/Featherless may reject an unknown field) → Qwen endpoints only.
        # This keeps the DashScope cloud AND self-hosted Ollama bodies byte-identical.
        _qwen_endpoint = self._endpoint in ("dashscope", "ollama")
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"
            body["parallel_tool_calls"] = True
            if _qwen_endpoint:
                body["enable_thinking"] = False
        elif json_mode:
            body["response_format"] = {"type": "json_object"}
            if _qwen_endpoint:
                body["enable_thinking"] = False
        # A self-hosted Ollama endpoint disables Qwen3 thinking via reasoning_effort:'none'
        # (it ignores enable_thinking). DashScope uses enable_thinking; OpenRouter and
        # Featherless reject the 'none' value, so this stays Ollama-only.
        if self._endpoint == "ollama":
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
