"""The native Hermes auxiliary protocol stays separate from production JSON."""

from test_evaluation import make_record
from test_runner import RecordingTokenizer

from agent_toolcall_sft.evaluation.native_hermes import (
    NATIVE_HERMES_PROMPT_VERSION,
    build_native_prompt,
    build_native_tool_specs,
    select_native_records,
)
from agent_toolcall_sft.evaluation.run_native_hermes_baseline import build_parser
from agent_toolcall_sft.evaluation.scoring import native_auxiliary_metrics, score_record


def test_native_prompt_uses_chat_template_tools_argument():
    tokenizer = RecordingTokenizer()
    record = make_record(tools=["get_order_status"])

    assert build_native_prompt(tokenizer, record) == "rendered"
    assert tokenizer.kwargs["tools"][0]["function"]["name"] == "get_order_status"
    assert NATIVE_HERMES_PROMPT_VERSION == "native_hermes_v1"


def test_native_tool_specs_cover_only_offered_tools_in_stable_order():
    specs = build_native_tool_specs(["summary_tool", "get_order_status"])
    assert [spec["function"]["name"] for spec in specs] == [
        "get_order_status",
        "summary_tool",
    ]
    assert all(spec["type"] == "function" for spec in specs)
    assert "properties" in specs[0]["function"]["parameters"]


def test_native_selection_keeps_only_gold_tool_calls_in_order():
    tool_a = make_record(id="a")
    non_tool = make_record(
        id="b",
        expected_action="clarify",
        expected_decision={"action": "clarify", "question": "请补充信息。"},
    )
    tool_c = make_record(id="c")

    selected = select_native_records([tool_a, non_tool, tool_c])

    assert [record.id for record in selected] == ["a", "c"]


def test_native_metrics_do_not_publish_main_behavior_accuracy():
    score = score_record(make_record(), "not json")
    metrics = native_auxiliary_metrics([score])

    assert metrics["n"] == 1
    assert "behavior_accuracy" not in metrics
    assert "end_to_end_accuracy" not in metrics
    assert "action_accuracy" not in metrics


def test_native_default_tag_cannot_be_confused_with_production():
    assert build_parser().parse_args([]).tag == "native-hermes-v1"
