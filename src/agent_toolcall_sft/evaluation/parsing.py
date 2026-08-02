"""Turn raw model text into a validated decision, in two separable stages.

The two stages stay separate on purpose. ROADMAP 3.1 reports "JSON 合法率" and
"工具 Schema 合法率" as different numbers, and collapsing both failures into a
single exception would make them impossible to tell apart: a model that emits
prose needs a different fix from one that emits well-formed but illegal calls.

Nothing here ever discards a sample. An unparseable output is a failed sample,
not a missing one -- dropping it would shrink the denominator and quietly
inflate every rate computed from it.
"""

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from agent_toolcall_sft.contracts import Decision, parse_decision

_FENCE = "```"


@dataclass(frozen=True)
class ParseResult:
    """What happened when we tried to read one model output."""

    raw: str
    json_ok: bool
    schema_ok: bool
    raw_tool_name: str | None = None
    decision: Decision | None = None
    error: str | None = None


def extract_json_block(text: str) -> str | None:
    """Pull the first balanced JSON object out of free-form model output.

    Small models wrap their answer in prose or in a fenced code block far more
    often than they emit bare JSON, and refusing those would measure output
    formatting rather than routing. Brace matching is enough here because the
    contract has no string field that may contain an unescaped brace.
    """
    body = text
    if _FENCE in body:
        segments = body.split(_FENCE)
        for segment in segments[1:]:
            candidate = segment.split("\n", 1)[-1] if segment[:4].isalpha() else segment
            if "{" in candidate:
                body = candidate
                break

    start = body.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(body)):
        char = body[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return body[start : index + 1]

    return None


_TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def extract_native_tool_call(text: str) -> str | None:
    """Pull the payload out of Qwen3's native <tool_call> block."""
    match = _TOOL_CALL_TAG.search(text)

    return match.group(1) if match else None


def _extract_raw_tool_name(payload: dict, *, native: bool) -> str | None:
    """Read an untrusted routing name without treating its arguments as valid."""
    if native or ("name" in payload and "action" not in payload):
        name = payload.get("name")
    else:
        tool_call = payload.get("tool_call")
        name = tool_call.get("name") if isinstance(tool_call, dict) else None

    return name if isinstance(name, str) else None


def parse_output(raw: str) -> ParseResult:
    """Read one raw model output, reporting which stage failed."""
    # A native <tool_call> block wins when present: that is what the chat
    # template asks for. A bare JSON object still parses, so a model that
    # answers in the plain envelope is not penalised for the wrapper.
    native = extract_native_tool_call(raw)
    block = native or extract_json_block(raw)
    if block is None:
        return ParseResult(
            raw,
            json_ok=False,
            schema_ok=False,
            raw_tool_name=None,
            error="no JSON object",
        )

    try:
        payload = json.loads(block)
    except json.JSONDecodeError as error:
        return ParseResult(
            raw,
            json_ok=False,
            schema_ok=False,
            raw_tool_name=None,
            error=str(error),
        )

    if not isinstance(payload, dict):
        return ParseResult(
            raw,
            json_ok=True,
            schema_ok=False,
            raw_tool_name=None,
            error="top level is not an object",
        )

    raw_tool_name = _extract_raw_tool_name(payload, native=native is not None)

    if native is not None or ("name" in payload and "action" not in payload):
        payload = {"action": "tool_call", "tool_call": payload}

    try:
        decision = parse_decision(payload)
    except ValidationError as error:
        return ParseResult(
            raw,
            json_ok=True,
            schema_ok=False,
            raw_tool_name=raw_tool_name,
            error=error.errors()[0]["msg"],
        )

    return ParseResult(
        raw,
        json_ok=True,
        schema_ok=True,
        raw_tool_name=raw_tool_name,
        decision=decision,
    )
