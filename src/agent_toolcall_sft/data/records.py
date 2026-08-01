"""Versioned dataset record schema for the tool-routing training data.

One record is the full description of one training example: the user turn,
the tool list that was offered for it, and the decision the model is expected
to produce. `expected_tool_call` reuses the contracts module so training
labels and evaluation checks are validated by exactly one definition.
"""

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator

from agent_toolcall_sft.contracts import ALL_TOOL_NAMES, Decision, StrictModel

Domain = Literal["knowledge", "support"]

ExpectedAction = Literal["tool_call", "clarify", "direct_answer", "handoff"]

# Patterns for real personal data that must never reach a generated record.
# The dataset is synthetic, so any hit means a template or an LLM rewrite
# leaked something it should not have.
PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"1[3-9]\d{9}"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    re.compile(r"\b\d{17}[\dXx]\b"),
)


def contains_pii(text: str) -> bool:
    """Return True when the text matches any known real-PII pattern."""
    return any(pattern.search(text) for pattern in PII_PATTERNS)


class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class Provenance(StrictModel):
    generator: Literal["rule", "rule+llm_rewrite"]
    template_version: str = Field(min_length=1)
    seed: int


class DatasetRecord(StrictModel):
    id: str = Field(min_length=1)
    scenario_family: str = Field(min_length=1)
    domain: Domain
    messages: list[Message] = Field(min_length=1)
    tools: list[str] = Field(min_length=1)
    expected_action: ExpectedAction
    expected_decision: Decision
    safety_tags: list[str] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def _reject_unknown_offered_tools(self) -> "DatasetRecord":
        unknown = sorted(set(self.tools) - ALL_TOOL_NAMES)
        if unknown:
            raise ValueError(f"tools contains unknown names: {unknown}")

        return self

    @model_validator(mode="after")
    def _require_action_to_match_decision(self) -> "DatasetRecord":
        if self.expected_action != self.expected_decision.action:
            raise ValueError(
                f"expected_action '{self.expected_action}' disagrees with "
                f"expected_decision.action '{self.expected_decision.action}'"
            )

        return self

    @model_validator(mode="after")
    def _require_tool_call_to_be_offered(self) -> "DatasetRecord":
        decision = self.expected_decision
        if decision.action == "tool_call" and decision.tool_call.name not in self.tools:
            raise ValueError(
                f"expected tool '{decision.tool_call.name}' "
                "was never offered in tools"
            )

        return self

    @model_validator(mode="after")
    def _reject_pii_in_messages(self) -> "DatasetRecord":
        for index, message in enumerate(self.messages):
            if contains_pii(message.content):
                raise ValueError(f"messages[{index}] contains a real-PII pattern")

        return self


def read_records(path: Path) -> list[DatasetRecord]:
    """Read and validate every record in a JSONL file.

    Blank lines are skipped. A malformed record raises immediately with the
    offending line number instead of being dropped silently.
    """
    records: list[DatasetRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                records.append(DatasetRecord.model_validate_json(line))
            except ValidationError as error:
                message = f"{path}:{line_number} is not a valid record"
                raise ValueError(message) from error

    return records


def write_records(path: Path, records: Iterable[DatasetRecord]) -> int:
    """Write records as JSONL and return how many lines were written."""
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json(exclude_none=True) + "\n")
            written += 1

    return written
