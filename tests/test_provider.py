"""Tests for aftershock.llm.provider — offline only, no real network calls."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from aftershock.kernel.protocol import TokenUsage
from aftershock.llm.provider import (
    MODEL_PRICES_USD_PER_MTOK,
    ChatResult,
    MockProvider,
    ProviderError,
    QwenProvider,
    _compute_cost,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_response(
    text: str = '{"decisions": []}',
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "qwen3.5-flash",
) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": text}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
        "model": model,
    }
    return httpx.Response(200, json=body)


def _status_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, text="error")


# ---------------------------------------------------------------------------
# QwenProvider construction
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="DASHSCOPE_API_KEY"):
        QwenProvider(api_key=None)


def test_explicit_api_key_does_not_raise() -> None:
    # Should not raise even with env cleared
    provider = QwenProvider(api_key="test-key-123")
    assert provider is not None


# ---------------------------------------------------------------------------
# JSON-mode request shaping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_json_mode_body_shape() -> None:
    """json_mode=True must add response_format json_object + enable_thinking false,
    and must NOT set max_tokens."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _ok_response()

    transport = httpx.MockTransport(handler)
    provider = QwenProvider(api_key="key", transport=transport, max_retries=0)

    with patch("asyncio.sleep"):
        await provider.chat(
            model="qwen3.5-flash",
            system="sys",
            user="usr",
            temperature=0.3,
            json_mode=True,
        )

    assert len(captured) == 1
    body = captured[0]
    assert body["response_format"] == {"type": "json_object"}
    assert body["enable_thinking"] is False
    assert "max_tokens" not in body


@pytest.mark.asyncio
async def test_non_json_mode_omits_response_format() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _ok_response()

    transport = httpx.MockTransport(handler)
    provider = QwenProvider(api_key="key", transport=transport, max_retries=0)

    with patch("asyncio.sleep"):
        await provider.chat(
            model="qwen3.5-flash",
            system="sys",
            user="usr",
            temperature=0.3,
            json_mode=False,
        )

    body = captured[0]
    assert "response_format" not in body
    assert "enable_thinking" not in body


# ---------------------------------------------------------------------------
# Authorization header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authorization_header_is_bearer() -> None:
    captured_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers)
        return _ok_response()

    transport = httpx.MockTransport(handler)
    provider = QwenProvider(api_key="my-secret-key", transport=transport, max_retries=0)

    with patch("asyncio.sleep"):
        await provider.chat(model="qwen3.5-flash", system="s", user="u", temperature=0.3)

    assert captured_headers[0]["authorization"] == "Bearer my-secret-key"


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_429_then_200_succeeds() -> None:
    responses = [_status_response(429), _ok_response()]
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        nonlocal call_count
        r = responses[call_count]
        call_count += 1
        return r

    transport = httpx.MockTransport(handler)
    provider = QwenProvider(api_key="key", transport=transport, max_retries=2)

    with patch("asyncio.sleep"):
        result = await provider.chat(model="qwen3.5-flash", system="s", user="u", temperature=0.3)

    assert isinstance(result, ChatResult)
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_429_three_times_raises_provider_error() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return _status_response(429)

    transport = httpx.MockTransport(handler)
    provider = QwenProvider(api_key="key", transport=transport, max_retries=2)

    with patch("asyncio.sleep"), pytest.raises(ProviderError):
        await provider.chat(model="qwen3.5-flash", system="s", user="u", temperature=0.3)

    # 1 initial + 2 retries = 3 total attempts
    assert call_count == 3


# ---------------------------------------------------------------------------
# Cost math
# ---------------------------------------------------------------------------


def test_cost_usd_math_qwen35_flash() -> None:
    """Verify cost calculation for qwen3.5-flash with known token counts."""
    prompt_tokens = 1000
    completion_tokens = 500
    model = "qwen3.5-flash"

    input_price, output_price = MODEL_PRICES_USD_PER_MTOK[model]
    expected_cost = (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000

    assert _compute_cost(model, prompt_tokens, completion_tokens) == pytest.approx(expected_cost)


@pytest.mark.asyncio
async def test_cost_usd_in_chat_result() -> None:
    """ChatResult.usage.cost_usd must match expected math from the mocked response."""
    prompt_tokens = 800
    completion_tokens = 200
    model = "qwen3.5-flash"

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return _ok_response(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
        )

    transport = httpx.MockTransport(handler)
    provider = QwenProvider(api_key="key", transport=transport, max_retries=0)

    with patch("asyncio.sleep"):
        result = await provider.chat(model=model, system="s", user="u", temperature=0.3)

    input_price, output_price = MODEL_PRICES_USD_PER_MTOK[model]
    expected = (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000

    assert result.usage.cost_usd == pytest.approx(expected)
    assert result.usage.prompt_tokens == prompt_tokens
    assert result.usage.completion_tokens == completion_tokens
    assert result.usage.model == model


def test_unknown_model_cost_is_zero() -> None:
    assert _compute_cost("unknown-model-xyz", 1000, 500) == 0.0


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_provider_records_calls() -> None:
    provider = MockProvider(script=["reply1", "reply2"])
    await provider.chat(model="m1", system="sys1", user="usr1", temperature=0.3)
    await provider.chat(model="m2", system="sys2", user="usr2", temperature=0.3)

    assert len(provider.calls) == 2
    assert provider.calls[0] == ("m1", "sys1", "usr1")
    assert provider.calls[1] == ("m2", "sys2", "usr2")


@pytest.mark.asyncio
async def test_mock_provider_len_div_4_token_counts() -> None:
    system = "a" * 40  # 40 chars → 10 prompt tokens
    text = "b" * 20  # 20 chars → 5 completion tokens
    provider = MockProvider(script=[text])

    result = await provider.chat(model="qwen3.5-flash", system=system, user="u", temperature=0.3)

    assert result.usage.prompt_tokens == len(system) // 4
    assert result.usage.completion_tokens == len(text) // 4


@pytest.mark.asyncio
async def test_mock_provider_cost_math() -> None:
    system = "x" * 400  # 100 prompt tokens
    text = "y" * 200  # 50 completion tokens
    model = "qwen3.5-flash"
    provider = MockProvider(script=[text])

    result = await provider.chat(model=model, system=system, user="u", temperature=0.3)

    prompt_tokens = len(system) // 4
    completion_tokens = len(text) // 4
    input_price, output_price = MODEL_PRICES_USD_PER_MTOK[model]
    expected = (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000

    assert result.usage.cost_usd == pytest.approx(expected)


@pytest.mark.asyncio
async def test_mock_provider_callable_script() -> None:
    def script(model: str, system: str, user: str) -> str:
        return f"echo:{model}"

    provider = MockProvider(script=script)
    result = await provider.chat(model="qwen3.5-flash", system="s", user="u", temperature=0.3)
    assert result.text == "echo:qwen3.5-flash"


@pytest.mark.asyncio
async def test_mock_provider_exhausted_raises() -> None:
    provider = MockProvider(script=["only-one"])
    await provider.chat(model="m", system="s", user="u", temperature=0.3)
    with pytest.raises(ProviderError, match="exhausted"):
        await provider.chat(model="m", system="s", user="u", temperature=0.3)


@pytest.mark.asyncio
async def test_mock_provider_usage_is_token_usage() -> None:
    provider = MockProvider(script=["hello"])
    result = await provider.chat(model="qwen-plus", system="s", user="u", temperature=0.3)
    assert isinstance(result.usage, TokenUsage)


# ---------------------------------------------------------------------------
# Tool-mode request shaping and response parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_mode_request_shape() -> None:
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return _tool_ok_response()

    transport = httpx.MockTransport(handler)
    provider = QwenProvider(api_key="key", transport=transport, max_retries=0)

    with patch("asyncio.sleep"):
        await provider.chat(
            model="qwen3.5-flash",
            system="sys",
            user="usr",
            temperature=0.3,
            json_mode=False,
            tools=[{"type": "function", "function": {"name": "test_tool", "parameters": {}}}],
            tool_choice="auto",
        )

    body = captured[0]
    assert "tools" in body
    assert body["tool_choice"] == "auto"
    assert body["parallel_tool_calls"] is True
    assert body["enable_thinking"] is False
    assert "response_format" not in body


def _tool_ok_response() -> httpx.Response:
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "test_tool",
                                "arguments": '{"key": "value"}',
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "model": "qwen3.5-flash",
    }
    return httpx.Response(200, json=body)


@pytest.mark.asyncio
async def test_tool_calls_parsed_from_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return _tool_ok_response()

    transport = httpx.MockTransport(handler)
    provider = QwenProvider(api_key="key", transport=transport, max_retries=0)

    with patch("asyncio.sleep"):
        result = await provider.chat(
            model="qwen3.5-flash",
            system="sys",
            user="usr",
            temperature=0.3,
            json_mode=False,
            tools=[{"type": "function", "function": {"name": "test_tool", "parameters": {}}}],
        )

    assert result.text == ""
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["function"]["name"] == "test_tool"
    assert result.usage.cost_usd > 0


@pytest.mark.asyncio
async def test_mock_provider_accepts_tool_calls_dict() -> None:
    tool_calls = [
        {
            "function": {
                "name": "no_op",
                "arguments": "{}",
            }
        }
    ]
    provider = MockProvider(script=[{"tool_calls": tool_calls}])

    result = await provider.chat(
        model="qwen3.5-flash",
        system="sys",
        user="usr",
        temperature=0.3,
        tools=[{"type": "function", "function": {"name": "no_op", "parameters": {}}}],
    )

    assert result.text == ""
    assert result.tool_calls == tool_calls
    assert len(provider.calls) == 1
