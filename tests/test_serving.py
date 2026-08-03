"""The router API must fail closed, and fail *distinguishably*.

A malformed model output and a genuine handoff decision look similar from the
outside and mean opposite things: one is a fault the caller should degrade
around, the other is a decision the caller should act on. These tests pin that
boundary.
"""

import json

import pytest
from fastapi.testclient import TestClient

from agent_toolcall_sft.serving.app import create_app
from agent_toolcall_sft.serving.backend import FakeBackend

ADAPTER = {"name": "qwen3-1.7b-toolcall-v2", "revision": "8109961df2e1"}


def client(output: str) -> TestClient:
    return TestClient(create_app(FakeBackend(output), adapter=ADAPTER))


def route(output: str, tools=None, message="订单 ORD-123456 到哪了？"):
    return client(output).post(
        "/v1/route",
        json={
            "messages": [{"role": "user", "content": message}],
            "tools": tools if tools is not None else ["get_order_status", "retrieval_tool"],
        },
    )


TOOL_CALL = json.dumps(
    {
        "action": "tool_call",
        "tool_call": {"name": "get_order_status", "arguments": {"order_id": "ORD-123456"}},
    },
    ensure_ascii=False,
)


def test_health_reports_the_loaded_adapter():
    response = client(TOOL_CALL).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["adapter_revision"] == "8109961df2e1"
    assert body["model_version"] == "qwen3-1.7b-toolcall-v2"


def test_a_valid_tool_call_round_trips():
    response = route(TOOL_CALL)

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["action"] == "tool_call"
    assert body["decision"]["tool_call"]["name"] == "get_order_status"
    assert body["decision"]["tool_call"]["arguments"]["order_id"] == "ORD-123456"
    assert body["adapter_revision"] == "8109961df2e1"
    assert body["latency_ms"] >= 0


@pytest.mark.parametrize(
    "action,payload",
    [
        ("clarify", {"action": "clarify", "question": "请提供订单号。"}),
        ("direct_answer", {"action": "direct_answer", "answer": "在的。"}),
        ("handoff", {"action": "handoff", "reason": "超出业务范围。"}),
    ],
)
def test_non_tool_decisions_are_returned_as_decisions(action, payload):
    response = route(json.dumps(payload, ensure_ascii=False))

    assert response.status_code == 200
    assert response.json()["decision"]["action"] == action


def test_a_genuine_handoff_is_not_confused_with_a_failure():
    """handoff is a decision to act on; a fault must never be dressed up as one."""
    ok = route(json.dumps({"action": "handoff", "reason": "越权请求。"}, ensure_ascii=False))
    broken = route("这不是 JSON")

    assert ok.status_code == 200
    assert broken.status_code == 422
    assert "decision" not in broken.json()


def test_unparsable_output_fails_closed():
    response = route("模型今天不太舒服")

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_json"


def test_schema_invalid_output_fails_closed():
    response = route(json.dumps({"action": "get_order_status", "arguments": {}}))

    assert response.status_code == 422
    assert response.json()["error"] == "schema_invalid"


def test_a_tool_outside_the_offered_list_fails_closed():
    response = route(TOOL_CALL, tools=["retrieval_tool"])

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "off_menu_tool"
    assert "get_order_status" in body["detail"]


def test_unconfirmed_refund_cannot_pass():
    """confirmed is Literal[True]; an unconfirmed refund is unrepresentable."""
    response = route(
        json.dumps(
            {
                "action": "tool_call",
                "tool_call": {
                    "name": "create_refund_request",
                    "arguments": {"order_id": "ORD-123456", "reason": "damaged_item", "confirmed": False},
                },
            }
        ),
        tools=["create_refund_request"],
    )

    assert response.status_code == 422
    assert response.json()["error"] == "schema_invalid"


def test_missing_argument_fails_closed():
    response = route(
        json.dumps({"action": "tool_call", "tool_call": {"name": "get_order_status", "arguments": {}}}),
    )

    assert response.status_code == 422
    assert response.json()["error"] == "schema_invalid"


def test_the_failure_body_carries_the_raw_output_for_the_caller_to_log():
    response = route("坏输出")

    assert response.json()["raw_output"] == "坏输出"


def test_an_unknown_tool_in_the_request_is_rejected():
    response = route(TOOL_CALL, tools=["get_order_status", "not_a_real_tool"])

    assert response.status_code == 422


def test_an_empty_tool_list_is_rejected():
    assert route(TOOL_CALL, tools=[]).status_code == 422
