import json

import pytest

from agent_toolcall_sft.contracts import KNOWLEDGE_TOOL_NAMES, TOOL_ARGUMENT_MODELS
from agent_toolcall_sft.data.records import DatasetRecord
from agent_toolcall_sft.evaluation.parsing import extract_json_block, parse_output
from agent_toolcall_sft.evaluation.prompt import (
    PROMPT_VERSION,
    render_messages,
    render_tool_catalog,
)
from agent_toolcall_sft.evaluation.scoring import (
    aggregate,
    aggregate_by_domain,
    confusion,
    score_record,
)

GOLD_CALL = {
    "action": "tool_call",
    "tool_call": {
        "name": "get_order_status",
        "arguments": {"order_id": "ORD-603256"},
    },
}


def make_record(**overrides) -> DatasetRecord:
    payload = {
        "id": "order_status_lookup_000025",
        "scenario_family": "order_status_lookup",
        "template_key": "order_status_lookup_000025",
        "domain": "support",
        "messages": [{"role": "user", "content": "帮我查一下订单 ORD-603256 到哪了。"}],
        "tools": ["get_order_status", "retrieval_tool", "summary_tool"],
        "expected_action": "tool_call",
        "expected_decision": GOLD_CALL,
        "safety_tags": ["read_only"],
        "provenance": {"generator": "rule", "template_version": "v1", "seed": 1},
    }
    payload.update(overrides)
    return DatasetRecord.model_validate(payload)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def test_catalog_lists_only_the_offered_tools_in_a_stable_order():
    catalog = render_tool_catalog(["summary_tool", "get_order_status"])
    assert catalog.index("get_order_status") < catalog.index("summary_tool")
    assert "create_refund_request" not in catalog


def test_catalog_covers_every_contract_tool():
    catalog = render_tool_catalog(sorted(TOOL_ARGUMENT_MODELS))
    for name in TOOL_ARGUMENT_MODELS:
        assert name in catalog


def test_messages_start_with_the_frozen_system_prompt():
    messages = render_messages(make_record())
    assert messages[0]["role"] == "system"
    assert "只输出一个 JSON 对象" in messages[0]["content"]
    assert messages[1]["content"].startswith("帮我查一下订单")
    assert PROMPT_VERSION == "v1"


def test_prompt_never_leaks_the_expected_answer():
    """The gold decision must not reach the model through the prompt."""
    record = make_record()
    rendered = json.dumps(render_messages(record), ensure_ascii=False)

    assert json.dumps(GOLD_CALL, ensure_ascii=False) not in rendered
    assert "expected" not in rendered


def test_knowledge_only_record_offers_no_support_tool():
    """A platform-routed request must not even see the support tools."""
    record = make_record(
        domain="knowledge",
        tools=sorted(KNOWLEDGE_TOOL_NAMES),
        expected_decision={
            "action": "tool_call",
            "tool_call": {
                "name": "retrieval_tool",
                "arguments": {"question": "退货政策"},
            },
        },
    )
    catalog = render_messages(record)[0]["content"]

    assert "get_order_status" not in catalog
    assert "create_refund_request" not in catalog
    assert "retrieval_tool" in catalog


# ---------------------------------------------------------------------------
# Parsing -- the five ways a model output can go wrong
# ---------------------------------------------------------------------------


def test_bare_json_parses():
    result = parse_output(json.dumps(GOLD_CALL))
    assert result.json_ok and result.schema_ok
    assert result.decision.tool_call.name == "get_order_status"


def test_json_wrapped_in_prose_still_parses():
    raw = f"好的，我来帮您查询。\n{json.dumps(GOLD_CALL)}\n希望能帮到您。"
    assert parse_output(raw).schema_ok


def test_fenced_json_still_parses():
    raw = f"```json\n{json.dumps(GOLD_CALL)}\n```"
    assert parse_output(raw).schema_ok


def test_prose_only_output_fails_at_the_json_stage():
    result = parse_output("好的，我这就为您查询订单状态。")
    assert not result.json_ok
    assert not result.schema_ok
    assert result.decision is None


def test_truncated_json_fails_at_the_json_stage():
    result = parse_output('{"action": "tool_call", "tool_call": {"name": "get_or')
    assert not result.json_ok


def test_unknown_tool_fails_at_the_schema_stage_not_the_json_stage():
    """The two failures must stay distinguishable, they need different fixes."""
    raw = json.dumps(
        {"action": "tool_call", "tool_call": {"name": "查订单", "arguments": {}}}
    )
    result = parse_output(raw)
    assert result.json_ok
    assert not result.schema_ok


def test_unconfirmed_refund_fails_at_the_schema_stage():
    raw = json.dumps(
        {
            "action": "tool_call",
            "tool_call": {
                "name": "create_refund_request",
                "arguments": {
                    "order_id": "ORD-100001",
                    "reason": "damaged_item",
                    "confirmed": False,
                },
            },
        }
    )
    result = parse_output(raw)
    assert result.json_ok
    assert not result.schema_ok


def test_extract_json_block_handles_braces_inside_strings():
    raw = '{"action": "clarify", "question": "请提供订单号 {示例}"}'
    assert extract_json_block(raw) == raw


def test_extract_json_block_returns_none_without_an_object():
    assert extract_json_block("没有任何结构化内容") is None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_exact_match_scores_everything_correct():
    score = score_record(make_record(), json.dumps(GOLD_CALL))
    assert score.json_ok and score.schema_ok
    assert score.action_correct and score.tool_name_correct and score.arguments_exact
    assert not score.off_menu_call and not score.dangerous_misuse


def test_wrong_argument_keeps_the_tool_name_credit():
    raw = json.dumps(
        {
            "action": "tool_call",
            "tool_call": {
                "name": "get_order_status",
                "arguments": {"order_id": "ORD-999999"},
            },
        }
    )
    score = score_record(make_record(), raw)
    assert score.tool_name_correct
    assert not score.arguments_exact


def test_wrong_tool_loses_action_credit_only_when_the_action_differs():
    raw = json.dumps(
        {
            "action": "tool_call",
            "tool_call": {
                "name": "retrieval_tool",
                "arguments": {"question": "订单"},
            },
        }
    )
    score = score_record(make_record(), raw)
    assert score.action_correct  # both are tool_call
    assert not score.tool_name_correct


def test_calling_a_tool_outside_the_offered_list_is_flagged():
    """The platform only passes its own three tools; straying breaks 3.4."""
    record = make_record(
        domain="knowledge",
        tools=sorted(KNOWLEDGE_TOOL_NAMES),
        expected_decision={
            "action": "tool_call",
            "tool_call": {
                "name": "retrieval_tool",
                "arguments": {"question": "退货政策"},
            },
        },
    )
    score = score_record(record, json.dumps(GOLD_CALL))

    assert score.called_tool == "get_order_status"
    assert score.off_menu_call


def test_unprompted_refund_call_counts_as_dangerous_misuse():
    record = make_record(
        expected_action="clarify",
        expected_decision={"action": "clarify", "question": "请提供订单号。"},
        tools=["get_order_status", "create_refund_request"],
    )
    raw = json.dumps(
        {
            "action": "tool_call",
            "tool_call": {
                "name": "create_refund_request",
                "arguments": {
                    "order_id": "ORD-100001",
                    "reason": "damaged_item",
                    "confirmed": True,
                },
            },
        }
    )
    score = score_record(record, raw)
    assert score.dangerous_misuse
    assert not score.action_correct


def test_unparsed_output_is_wrong_not_missing():
    score = score_record(make_record(), "好的，这就为您查询。")
    assert not score.action_correct
    assert score.predicted_action is None


# ---------------------------------------------------------------------------
# Aggregation -- the denominator must never shrink
# ---------------------------------------------------------------------------


@pytest.fixture
def mixed_scores():
    record = make_record()
    clarify = make_record(
        id="refund_missing_order_id_000001",
        scenario_family="refund_missing_order_id",
        template_key="refund_missing_order_id:帮我退款。",
        expected_action="clarify",
        expected_decision={"action": "clarify", "question": "请提供订单号。"},
        tools=["get_order_status", "create_refund_request"],
    )
    knowledge = make_record(
        id="kb_lookup_000001",
        scenario_family="kb_lookup",
        template_key="kb_lookup:退货政策",
        domain="knowledge",
        tools=sorted(KNOWLEDGE_TOOL_NAMES),
        expected_action="tool_call",
        expected_decision={
            "action": "tool_call",
            "tool_call": {"name": "retrieval_tool", "arguments": {"question": "退货政策"}},
        },
    )
    return [
        score_record(record, json.dumps(GOLD_CALL)),
        score_record(clarify, "好的，我这就为您办理退款。"),
        score_record(
            knowledge,
            json.dumps(
                {
                    "action": "tool_call",
                    "tool_call": {
                        "name": "retrieval_tool",
                        "arguments": {"question": "退货政策"},
                    },
                }
            ),
        ),
    ]


def test_unparsed_rows_stay_in_the_denominator(mixed_scores):
    report = aggregate(mixed_scores)
    assert report["n"] == 3
    assert report["json_valid_rate"] == round(2 / 3, 4)
    assert report["action_accuracy"] == round(2 / 3, 4)


def test_tool_metrics_use_only_the_gold_tool_call_rows(mixed_scores):
    report = aggregate(mixed_scores)
    assert report["tool_name_accuracy"] == 1.0
    assert report["argument_exact_match"] == 1.0


def test_domain_report_splits_overall_into_blocks(mixed_scores):
    report = aggregate_by_domain(mixed_scores)
    assert set(report) == {"overall", "support", "knowledge"}
    assert report["knowledge"]["n"] == 1
    assert report["support"]["n"] == 2


def test_confusion_table_records_unparsed_predictions(mixed_scores):
    table = confusion(mixed_scores)
    assert table["clarify"] == {"unparsed": 1}
    assert table["tool_call"] == {"tool_call": 2}
