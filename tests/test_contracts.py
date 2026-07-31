import pytest
from pydantic import ValidationError

from agent_toolcall_sft.contracts import parse_decision


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
