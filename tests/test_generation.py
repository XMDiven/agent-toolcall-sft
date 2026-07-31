import random
import re

import pytest

from agent_toolcall_sft.contracts import ALL_TOOL_NAMES, ORDER_ID_PATTERN
from agent_toolcall_sft.data.generation import (
    REFUND_CONFIRMED,
    TEMPLATE_VERSION,
    generate_family,
    offer_tools,
)


@pytest.fixture
def refund_records():
    return generate_family(REFUND_CONFIRMED, count=50, seed_base=1000)


def test_same_seed_base_reproduces_identical_records(refund_records):
    again = generate_family(REFUND_CONFIRMED, count=50, seed_base=1000)
    assert again == refund_records


def test_different_seed_base_changes_content(refund_records):
    other = generate_family(REFUND_CONFIRMED, count=50, seed_base=2000)
    assert [r.messages[0].content for r in other] != [
        r.messages[0].content for r in refund_records
    ]


def test_ids_are_unique_and_family_tagged(refund_records):
    ids = [record.id for record in refund_records]
    assert len(set(ids)) == len(ids)
    assert all(record.scenario_family == "refund_confirmed" for record in refund_records)


def test_provenance_records_the_seed_that_built_each_record(refund_records):
    assert [r.provenance.seed for r in refund_records] == list(range(1000, 1050))
    assert all(r.provenance.generator == "rule" for r in refund_records)
    assert all(
        r.provenance.template_version == TEMPLATE_VERSION for r in refund_records
    )


def test_expected_tool_is_always_offered(refund_records):
    for record in refund_records:
        assert record.expected_tool_call.name in record.tools


def test_order_id_is_synthetic_and_appears_in_the_message(refund_records):
    for record in refund_records:
        order_id = record.expected_tool_call.arguments.order_id
        assert re.match(ORDER_ID_PATTERN, order_id)
        assert order_id in record.messages[0].content


def test_every_record_is_a_confirmed_write_call(refund_records):
    for record in refund_records:
        assert record.expected_action == "tool_call"
        assert record.expected_tool_call.name == "create_refund_request"
        assert record.expected_tool_call.arguments.confirmed is True
        assert "write_tool" in record.safety_tags


def test_offer_tools_always_contains_the_required_tool():
    for seed in range(20):
        tools = offer_tools(random.Random(seed), required="get_order_status")
        assert "get_order_status" in tools
        assert set(tools) <= ALL_TOOL_NAMES
        assert len(set(tools)) == len(tools)


def test_family_produces_more_than_one_distinct_sentence(refund_records):
    sentences = {record.messages[0].content for record in refund_records}
    assert len(sentences) > 1


def test_order_id_is_not_always_at_the_same_position():
    """A single sentence skeleton would let the model learn a positional cue."""
    records = generate_family(REFUND_CONFIRMED, count=200, seed_base=5000)
    positions = {
        record.messages[0].content.index(record.expected_tool_call.arguments.order_id)
        for record in records
    }
    assert len(positions) >= 4
