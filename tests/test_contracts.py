from typing import get_args

import pytest
from pydantic import ValidationError

from agent_toolcall_sft.contracts import ALL_TOOL_NAMES, ToolCall, parse_decision


def _refund_payload(**overrides):
    """Build a valid refund decision, with optional broken arguments."""
    arguments = {
        "order_id": "ORD-100001",
        "reason": "damaged_item",
        "confirmed": True,
    }
    arguments.update(overrides)
    return {
        "action": "tool_call",
        "tool_call": {"name": "create_refund_request", "arguments": arguments},
    }


def test_confirmed_refund_is_accepted():
    decision = parse_decision(_refund_payload())
    assert decision.action == "tool_call"
    assert decision.tool_call.name == "create_refund_request"
    assert decision.tool_call.arguments.order_id == "ORD-100001"


def test_retrieval_tool_matches_platform_signature():
    decision = parse_decision(
        {
            "action": "tool_call",
            "tool_call": {
                "name": "retrieval_tool",
                "arguments": {"question": "退货政策是什么"},
            },
        }
    )
    assert decision.tool_call.arguments.question == "退货政策是什么"


def test_unknown_tool_is_rejected():
    with pytest.raises(ValidationError):
        parse_decision(
            {
                "action": "tool_call",
                "tool_call": {"name": "delete_everything", "arguments": {}},
            }
        )


def test_unconfirmed_refund_is_rejected():
    with pytest.raises(ValidationError):
        parse_decision(_refund_payload(confirmed=False))


def test_malformed_order_id_is_rejected():
    with pytest.raises(ValidationError):
        parse_decision(_refund_payload(order_id="12345"))


def test_refund_without_order_id_is_rejected():
    payload = _refund_payload()
    del payload["tool_call"]["arguments"]["order_id"]
    with pytest.raises(ValidationError):
        parse_decision(payload)


def test_extra_argument_is_rejected():
    with pytest.raises(ValidationError):
        parse_decision(_refund_payload(admin=True))


def test_name_constants_stay_in_sync_with_the_tool_union():
    members = get_args(get_args(ToolCall)[0])
    tags = {
        get_args(member.model_fields["name"].annotation)[0] for member in members
    }
    assert tags == ALL_TOOL_NAMES


@pytest.mark.parametrize(
    "summary",
    [
        "请联系 13800138000",
        "请联系 user@example.com",
        "身份证是 11010119900307561X",
    ],
    ids=["phone", "email", "identity-card"],
)
def test_support_ticket_summary_rejects_real_pii(summary):
    with pytest.raises(ValidationError):
        parse_decision(
            {
                "action": "tool_call",
                "tool_call": {
                    "name": "create_support_ticket",
                    "arguments": {"summary": summary},
                },
            }
        )


@pytest.mark.parametrize(
    "summary",
    [
        "11010120000307561X",
        "身份证是11010120000307561X",
        "证件：11010120000307561X。",
    ],
    ids=["whole-string", "adjacent-chinese", "adjacent-punctuation"],
)
def test_support_ticket_summary_rejects_identity_card_at_text_boundaries(summary):
    with pytest.raises(ValidationError):
        parse_decision(
            {
                "action": "tool_call",
                "tool_call": {
                    "name": "create_support_ticket",
                    "arguments": {"summary": summary},
                },
            }
        )


@pytest.mark.parametrize(
    ("name", "argument", "text"),
    [
        ("retrieval_tool", "question", "客服电话是 13800138000 吗"),
        ("summary_tool", "text", "联系邮箱是 user@example.com"),
        ("question_decompose_tool", "question", "身份证 11010119900307561X 怎么改"),
    ],
)
def test_knowledge_tools_accept_dispatch_compatible_nonempty_strings(
    name, argument, text
):
    decision = parse_decision(
        {
            "action": "tool_call",
            "tool_call": {
                "name": name,
                "arguments": {argument: text},
            },
        }
    )
    assert getattr(decision.tool_call.arguments, argument) == text


@pytest.mark.parametrize(
    "arguments",
    [{"question": ""}, {"question": "退货政策", "extra": True}],
    ids=["empty", "extra"],
)
def test_knowledge_tools_keep_local_strict_validation(arguments):
    with pytest.raises(ValidationError):
        parse_decision(
            {
                "action": "tool_call",
                "tool_call": {
                    "name": "retrieval_tool",
                    "arguments": arguments,
                },
            }
        )


def test_ordinary_free_text_still_passes():
    decision = parse_decision(
        {
            "action": "tool_call",
            "tool_call": {
                "name": "create_support_ticket",
                "arguments": {"summary": "订单 ORD-100001 的发票下载不了"},
            },
        }
    )
    assert decision.tool_call.arguments.summary.startswith("订单")
