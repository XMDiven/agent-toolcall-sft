import pytest
from pydantic import ValidationError

from agent_toolcall_sft.contracts import KNOWLEDGE_TOOL_NAMES
from agent_toolcall_sft.data.records import (
    DatasetRecord,
    contains_pii,
    read_records,
    write_records,
)


def _support_payload(**overrides):
    """Build a valid support-domain record, with optional broken fields."""
    payload = {
        "id": "refund_confirmed_000001",
        "scenario_family": "refund_confirmed",
        "domain": "support",
        "messages": [
            {"role": "user", "content": "订单 ORD-100001 收到时破损，我确认要退款"}
        ],
        "tools": ["get_order_status", "create_refund_request"],
        "expected_action": "tool_call",
        "expected_tool_call": {
            "name": "create_refund_request",
            "arguments": {
                "order_id": "ORD-100001",
                "reason": "damaged_item",
                "confirmed": True,
            },
        },
        "safety_tags": ["write_tool", "explicit_confirmation"],
        "provenance": {"generator": "rule", "template_version": "v1", "seed": 42},
    }
    payload.update(overrides)
    return payload


def _knowledge_payload(**overrides):
    """Build a valid knowledge-domain record offering only platform tools."""
    payload = {
        "id": "kb_lookup_000001",
        "scenario_family": "kb_lookup",
        "domain": "knowledge",
        "messages": [{"role": "user", "content": "你们的退货政策是什么"}],
        "tools": sorted(KNOWLEDGE_TOOL_NAMES),
        "expected_action": "tool_call",
        "expected_tool_call": {
            "name": "retrieval_tool",
            "arguments": {"question": "退货政策"},
        },
        "safety_tags": [],
        "provenance": {"generator": "rule", "template_version": "v1", "seed": 7},
    }
    payload.update(overrides)
    return payload


def test_valid_support_record_is_accepted():
    record = DatasetRecord.model_validate(_support_payload())
    assert record.domain == "support"
    assert record.expected_tool_call.name == "create_refund_request"


def test_valid_knowledge_record_is_accepted():
    record = DatasetRecord.model_validate(_knowledge_payload())
    assert record.domain == "knowledge"
    assert set(record.tools) == KNOWLEDGE_TOOL_NAMES


def test_clarify_record_without_tool_call_is_accepted():
    record = DatasetRecord.model_validate(
        _support_payload(expected_action="clarify", expected_tool_call=None)
    )
    assert record.expected_tool_call is None


def test_tool_call_not_offered_in_tools_is_rejected():
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(_support_payload(tools=["get_order_status"]))


def test_tool_call_action_without_tool_call_is_rejected():
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(_support_payload(expected_tool_call=None))


def test_clarify_action_carrying_tool_call_is_rejected():
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(_support_payload(expected_action="clarify"))


def test_unknown_offered_tool_is_rejected():
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(
            _support_payload(tools=["create_refund_request", "nuke_everything"])
        )


def test_unknown_domain_is_rejected():
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(_support_payload(domain="finance"))


def test_unknown_expected_action_is_rejected():
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(_support_payload(expected_action="escalate"))


def test_invalid_tool_arguments_are_rejected():
    payload = _support_payload()
    payload["expected_tool_call"]["arguments"]["confirmed"] = False
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(payload)


def test_missing_provenance_is_rejected():
    payload = _support_payload()
    del payload["provenance"]
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(payload)


def test_phone_number_in_message_is_rejected():
    with pytest.raises(ValidationError):
        DatasetRecord.model_validate(
            _support_payload(
                messages=[{"role": "user", "content": "我的手机号是 13800138000"}]
            )
        )


def test_contains_pii_flags_real_identifiers_only():
    assert contains_pii("联系我 13800138000")
    assert contains_pii("邮箱 someone@example.com")
    assert contains_pii("证件号 11010119900307561X")
    assert not contains_pii("订单 ORD-100001 收到时破损")


def test_jsonl_round_trip_preserves_records(tmp_path):
    records = [
        DatasetRecord.model_validate(_support_payload()),
        DatasetRecord.model_validate(_knowledge_payload()),
    ]
    path = tmp_path / "records.jsonl"

    assert write_records(path, records) == 2
    assert read_records(path) == records


def test_reading_a_malformed_line_reports_its_line_number(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"id": "broken"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"records\.jsonl:1"):
        read_records(path)
