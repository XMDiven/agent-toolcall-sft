import random
import re

import pytest

from agent_toolcall_sft.contracts import (
    ALL_TOOL_NAMES,
    KNOWLEDGE_TOOL_NAMES,
    ORDER_ID_PATTERN,
    SUPPORT_TOOL_NAMES,
)
from agent_toolcall_sft.data.generation import (
    KNOWLEDGE_FAMILIES,
    REFUND_CONFIRMED,
    TEMPLATE_VERSION,
    generate_family,
    offer_tools,
)

EXPECTED_KNOWLEDGE_TOOL = {
    "kb_lookup": "retrieval_tool",
    "kb_compare": "question_decompose_tool",
    "text_summarize": "summary_tool",
}


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


@pytest.fixture(params=KNOWLEDGE_FAMILIES, ids=lambda family: family.name)
def knowledge_records(request):
    return request.param, generate_family(request.param, count=200, seed_base=3000)


def test_knowledge_family_targets_its_platform_tool(knowledge_records):
    family, records = knowledge_records
    expected = EXPECTED_KNOWLEDGE_TOOL[family.name]
    for record in records:
        assert record.domain == "knowledge"
        assert record.expected_action == "tool_call"
        assert record.expected_tool_call.name == expected


def test_knowledge_argument_appears_verbatim_in_the_message(knowledge_records):
    """Exact-match scoring only means something if the target is quotable."""
    _, records = knowledge_records
    for record in records:
        arguments = record.expected_tool_call.arguments.model_dump()
        core = next(iter(arguments.values()))
        assert core in record.messages[0].content


def test_knowledge_family_emits_platform_only_tool_lists(knowledge_records):
    _, records = knowledge_records
    platform_only = [r for r in records if set(r.tools) <= KNOWLEDGE_TOOL_NAMES]
    assert platform_only, "no subset-routing samples were produced"

    for record in platform_only:
        assert not set(record.tools) & SUPPORT_TOOL_NAMES


def test_knowledge_family_is_reproducible(knowledge_records):
    family, records = knowledge_records
    assert generate_family(family, count=200, seed_base=3000) == records


def test_offer_tools_respects_a_narrowed_pool():
    for seed in range(20):
        tools = offer_tools(
            random.Random(seed), "retrieval_tool", pool=KNOWLEDGE_TOOL_NAMES
        )
        assert set(tools) <= KNOWLEDGE_TOOL_NAMES
        assert "retrieval_tool" in tools
