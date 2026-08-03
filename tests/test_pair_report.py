"""Pairing two runs must be an exact join, not a best-effort alignment."""

import pytest

from agent_toolcall_sft.evaluation.pair_report import pair_records

SCORE = {
    "record_id": "a",
    "domain": "support",
    "expected_action": "clarify",
    "expected_tool": None,
    "predicted_action": "clarify",
    "json_ok": True,
    "schema_ok": True,
    "action_correct": True,
    "tool_name_correct": None,
    "arguments_exact": None,
    "arguments_normalized": None,
    "called_tools": [],
    "dangerous_tool_available": False,
    "off_menu_call": False,
    "dangerous_misuse": False,
    "error": None,
}


def row(record_id: str, *, correct: bool, output: str = "{}"):
    score = dict(SCORE, record_id=record_id)
    if not correct:
        score["predicted_action"] = "handoff"
    return {
        "record_id": record_id,
        "domain": "support",
        "scenario_family": "greeting",
        "raw_output": output,
        "score": score,
    }


def test_transitions_are_labelled():
    base = [row("a", correct=False), row("b", correct=True), row("c", correct=True), row("d", correct=False)]
    tuned = [row("a", correct=True), row("b", correct=False), row("c", correct=True), row("d", correct=False)]

    labels = {r["record_id"]: r["transition"] for r in pair_records(base, tuned)}
    assert labels == {
        "a": "fixed",
        "b": "broken",
        "c": "both_correct",
        "d": "both_wrong",
    }


def test_a_missing_record_is_refused():
    with pytest.raises(ValueError, match="different records"):
        pair_records([row("a", correct=True), row("b", correct=True)], [row("a", correct=True)])


def test_a_renamed_record_is_refused():
    with pytest.raises(ValueError, match="different records"):
        pair_records([row("a", correct=True)], [row("z", correct=True)])


def test_base_order_is_preserved():
    base = [row("b", correct=True), row("a", correct=True)]
    tuned = [row("a", correct=True), row("b", correct=True)]

    assert [r["record_id"] for r in pair_records(base, tuned)] == ["b", "a"]


def test_both_outputs_are_carried_through():
    paired = pair_records(
        [row("a", correct=False, output="base text")],
        [row("a", correct=True, output="tuned text")],
    )
    assert paired[0]["base_output"] == "base text"
    assert paired[0]["tuned_output"] == "tuned text"
