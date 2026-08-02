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


@dataclass(frozen=True)
class ParseResult:
    """What happened when we tried to read one model output."""

    raw: str
    json_ok: bool
    schema_ok: bool
    raw_called_tools: tuple[str, ...] = ()
    decision: Decision | None = None
    error: str | None = None

    @property
    def raw_tool_name(self) -> str | None:
        """Compatibility accessor for outputs with exactly one raw tool name."""
        return self.raw_called_tools[0] if len(self.raw_called_tools) == 1 else None


@dataclass(frozen=True)
class _JsonCandidate:
    start: int
    block: str
    complete: bool
    array_depth: int


def _array_depth_before(text: str, stop: int) -> int:
    """Count open JSON-array brackets before an object candidate."""
    depth = 0
    in_string = False
    escaped = False
    for char in text[:stop]:
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
        elif char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
    return depth


def _scan_json_objects(text: str, *, offset: int = 0) -> list[_JsonCandidate]:
    """Return every outermost brace-delimited object in textual order.

    Nested argument objects stay inside their parent candidate. String content,
    escaped quotes, and escaped backslashes do not affect brace depth. An
    unfinished final object is retained so the JSON stage can fail explicitly
    instead of silently accepting an earlier complete decision.
    """
    candidates: list[_JsonCandidate] = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start == -1:
            break

        depth = 0
        in_string = False
        escaped = False
        end = None
        for cursor in range(start, len(text)):
            char = text[cursor]
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
                    end = cursor + 1
                    break

        if end is None:
            candidates.append(
                _JsonCandidate(
                    offset + start,
                    text[start:],
                    complete=False,
                    array_depth=_array_depth_before(text, start),
                )
            )
            break

        candidates.append(
            _JsonCandidate(
                offset + start,
                text[start:end],
                complete=True,
                array_depth=_array_depth_before(text, start),
            )
        )
        index = end

    return candidates


def extract_json_block(text: str) -> str | None:
    """Pull the first complete balanced JSON object from free-form text."""
    candidates = _scan_json_objects(text)
    if not candidates or not candidates[0].complete:
        return None
    return candidates[0].block


_TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def extract_native_tool_call(text: str) -> str | None:
    """Pull the payload out of Qwen3's native <tool_call> block."""
    match = _TOOL_CALL_TAG.search(text)

    return match.group(1) if match else None


def _extract_candidates(raw: str) -> list[_JsonCandidate]:
    """Collect native and ordinary objects once, preserving source order."""
    candidates: list[_JsonCandidate] = []
    ordinary_start = 0
    for match in _TOOL_CALL_TAG.finditer(raw):
        candidates.extend(
            _scan_json_objects(
                raw[ordinary_start : match.start()], offset=ordinary_start
            )
        )
        candidates.extend(
            _scan_json_objects(match.group(1), offset=match.start(1))
        )
        ordinary_start = match.end()
    candidates.extend(_scan_json_objects(raw[ordinary_start:], offset=ordinary_start))
    return sorted(candidates, key=lambda candidate: candidate.start)


def _extract_raw_tool_names(payload: dict) -> tuple[str, ...]:
    """Read untrusted top-level and envelope routing names conservatively."""
    names = []
    top_level_name = payload.get("name")
    if isinstance(top_level_name, str):
        names.append(top_level_name)

    tool_call = payload.get("tool_call")
    nested_name = tool_call.get("name") if isinstance(tool_call, dict) else None
    if isinstance(nested_name, str) and nested_name not in names:
        names.append(nested_name)

    return tuple(names)


def _ordered_unique_tool_names(payloads: list[dict]) -> tuple[str, ...]:
    names: list[str] = []
    for payload in payloads:
        for name in _extract_raw_tool_names(payload):
            if name not in names:
                names.append(name)
    return tuple(names)


def parse_output(raw: str) -> ParseResult:
    """Read one raw model output, reporting which stage failed."""
    candidates = _extract_candidates(raw)
    if not candidates:
        return ParseResult(
            raw,
            json_ok=False,
            schema_ok=False,
            error="no JSON object",
        )

    payloads: list[dict] = []
    first_json_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate.block)
        except json.JSONDecodeError as error:
            first_json_error = first_json_error or error
            continue
        if isinstance(payload, dict):
            payloads.append(payload)

    raw_called_tools = _ordered_unique_tool_names(payloads)
    if first_json_error is not None or len(payloads) != len(candidates):
        return ParseResult(
            raw,
            json_ok=False,
            schema_ok=False,
            raw_called_tools=raw_called_tools,
            error=str(first_json_error or "top level is not an object"),
        )

    if any(candidate.array_depth for candidate in candidates):
        return ParseResult(
            raw,
            json_ok=False,
            schema_ok=False,
            raw_called_tools=raw_called_tools,
            error="top level is not an object",
        )

    if len(payloads) > 1:
        return ParseResult(
            raw,
            json_ok=True,
            schema_ok=False,
            raw_called_tools=raw_called_tools,
            error=f"multiple JSON objects ({len(payloads)})",
        )

    payload = payloads[0]
    if "name" in payload and "action" not in payload:
        payload = {"action": "tool_call", "tool_call": payload}

    try:
        decision = parse_decision(payload)
    except ValidationError as error:
        return ParseResult(
            raw,
            json_ok=True,
            schema_ok=False,
            raw_called_tools=raw_called_tools,
            error=error.errors()[0]["msg"],
        )

    return ParseResult(
        raw,
        json_ok=True,
        schema_ok=True,
        raw_called_tools=raw_called_tools,
        decision=decision,
    )
