"""Tolerant, strict-enough output parsing for LLM JSON responses.

Strips markdown fences, extracts the first balanced {...} block,
validates against the LLMOutput schema.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class LLMDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision_type: str
    params: dict[str, Any] = {}
    rationale: str = ""


class LLMProposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: str
    recipient: str | None = None
    body: dict[str, Any] = {}


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proposal_id: str
    accept: bool
    note: str = ""


class LLMOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decisions: list[LLMDecision] = []
    proposals: list[LLMProposal] = []
    responses: list[LLMResponse] = []


class LLMParseError(Exception):
    """Raised when the LLM output cannot be parsed or validated. Carries a short reason."""


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences, returning content inside them if present."""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text


def _first_balanced_brace(text: str) -> str:
    """Extract the first balanced {...} block from text, or raise LLMParseError.

    String-aware: brace counting is suspended inside JSON string literals so that
    a ``}`` or ``{`` inside a string value does not prematurely end or extend the
    extracted block.  Handles backslash escapes (e.g. ``\\"``) correctly.
    """
    start = text.find("{")
    if start == -1:
        raise LLMParseError("no JSON object found in output")
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text[start:], start):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise LLMParseError("unbalanced braces in output")


def parse_llm_output(text: str) -> LLMOutput:
    """Parse and validate LLM JSON output into LLMOutput.

    Steps:
    1. Strip markdown code fences.
    2. Extract the first balanced {...} block.
    3. json.loads the block.
    4. Validate with LLMOutput (extra fields ignored, unknown decision_types pass through).

    Raises LLMParseError with a short reason on any failure.
    """
    stripped = _strip_fences(text)
    block = _first_balanced_brace(stripped)

    try:
        data = json.loads(block)
    except json.JSONDecodeError as exc:
        raise LLMParseError(f"invalid JSON: {exc.msg}") from exc

    try:
        return LLMOutput.model_validate(data)
    except ValidationError as exc:
        # Extract first error message for brevity
        errors = exc.errors()
        reason = errors[0]["msg"] if errors else str(exc)
        raise LLMParseError(f"schema validation failed: {reason}") from exc
