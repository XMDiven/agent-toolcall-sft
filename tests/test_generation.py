import random
import re

import pytest

from agent_toolcall_sft.contracts import (
    ALL_TOOL_NAMES,
    DANGEROUS_TOOL_NAMES,
    KNOWLEDGE_TOOL_NAMES,
    ORDER_ID_PATTERN,
    SUPPORT_TOOL_NAMES,
)
from agent_toolcall_sft.data.families import (
    ALL_FAMILIES,
    CLARIFY_FAMILIES,
    DIRECT_ANSWER_FAMILIES,
    HANDOFF_FAMILIES,
    KNOWLEDGE_FAMILIES,
    REFUND_CONFIRMED,
    SAFETY_FAMILIES,
)
from agent_toolcall_sft.data.generation import (
    TEMPLATE_VERSION,
    generate_family,
    offer_idle_tools,
    offer_tools,
)

SAMPLE_COUNT = 120
SAMPLE_SEED = 3000

EXPECTED_KNOWLEDGE_TOOL = {
    "kb_lookup": "retrieval_tool",
    "kb_compare": "question_decompose_tool",
    "text_summarize": "summary_tool",
}


def _sample(family, count=SAMPLE_COUNT, seed_base=SAMPLE_SEED):
    return generate_family(family, count=count, seed_base=seed_base)


@pytest.fixture(params=ALL_FAMILIES, ids=lambda family: family.name)
def family_records(request):
    return request.param, _sample(request.param)


# ---------------------------------------------------------------------------
# Properties every family must hold
# ---------------------------------------------------------------------------


def test_every_family_is_reproducible(family_records):
    family, records = family_records
    assert _sample(family) == records


def test_every_family_tags_its_records(family_records):
    family, records = family_records
    ids = [record.id for record in records]
    assert len(set(ids)) == len(ids)
    for record in records:
        assert record.scenario_family == family.name
        assert record.domain == family.domain
        assert record.provenance.generator == "rule"
        assert record.provenance.template_version == TEMPLATE_VERSION


def test_every_family_records_the_seed_that_built_each_record(family_records):
    _, records = family_records
    expected = list(range(SAMPLE_SEED, SAMPLE_SEED + SAMPLE_COUNT))
    assert [record.provenance.seed for record in records] == expected


def test_every_family_offers_only_known_tools(family_records):
    _, records = family_records
    for record in records:
        assert set(record.tools) <= ALL_TOOL_NAMES
        assert len(set(record.tools)) == len(record.tools)


def test_every_family_produces_more_than_one_distinct_message(family_records):
    _, records = family_records
    assert len({record.messages[0].content for record in records}) > 1


# ---------------------------------------------------------------------------
# Per-category behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", KNOWLEDGE_FAMILIES, ids=lambda f: f.name)
def test_knowledge_family_targets_its_platform_tool(family):
    expected = EXPECTED_KNOWLEDGE_TOOL[family.name]
    for record in _sample(family):
        assert record.domain == "knowledge"
        assert record.expected_decision.tool_call.name == expected


@pytest.mark.parametrize("family", KNOWLEDGE_FAMILIES, ids=lambda f: f.name)
def test_knowledge_argument_appears_verbatim_in_the_message(family):
    """Exact-match scoring only means something if the target is quotable."""
    for record in _sample(family):
        arguments = record.expected_decision.tool_call.arguments.model_dump()
        core = next(iter(arguments.values()))
        assert core in record.messages[0].content


@pytest.mark.parametrize("family", KNOWLEDGE_FAMILIES, ids=lambda f: f.name)
def test_knowledge_family_emits_platform_only_tool_lists(family):
    records = _sample(family)
    platform_only = [r for r in records if set(r.tools) <= KNOWLEDGE_TOOL_NAMES]
    assert platform_only, "no subset-routing samples were produced"

    for record in platform_only:
        assert not set(record.tools) & SUPPORT_TOOL_NAMES


@pytest.mark.parametrize("family", CLARIFY_FAMILIES, ids=lambda f: f.name)
def test_clarify_family_never_calls_a_tool(family):
    for record in _sample(family):
        assert record.expected_action == "clarify"
        assert record.expected_decision.question


@pytest.mark.parametrize("family", DIRECT_ANSWER_FAMILIES, ids=lambda f: f.name)
def test_direct_answer_family_answers_without_a_tool(family):
    for record in _sample(family):
        assert record.expected_action == "direct_answer"
        assert record.expected_decision.answer


@pytest.mark.parametrize(
    "family", HANDOFF_FAMILIES + SAFETY_FAMILIES, ids=lambda f: f.name
)
def test_handoff_family_escalates_with_a_reason(family):
    for record in _sample(family):
        assert record.expected_action == "handoff"
        assert record.expected_decision.reason


def test_dangerous_tool_is_offered_but_withheld_in_unsafe_families():
    """The refund tool must be on the table, or refusing it proves nothing."""
    withholding = (
        *CLARIFY_FAMILIES,
        *SAFETY_FAMILIES,
    )
    for family in withholding:
        offered = [
            record
            for record in _sample(family)
            if set(record.tools) & DANGEROUS_TOOL_NAMES
        ]
        if not offered:
            continue

        for record in offered:
            assert record.expected_action != "tool_call"


def test_prompt_injection_never_produces_a_write_call():
    for family in SAFETY_FAMILIES:
        for record in _sample(family):
            assert record.expected_action == "handoff"


# ---------------------------------------------------------------------------
# refund_confirmed specifics
# ---------------------------------------------------------------------------


def test_refund_confirmed_is_always_a_confirmed_write_call():
    for record in _sample(REFUND_CONFIRMED):
        call = record.expected_decision.tool_call
        assert call.name == "create_refund_request"
        assert call.arguments.confirmed is True
        assert "write_tool" in record.safety_tags


def test_refund_order_id_is_synthetic_and_appears_in_the_message():
    for record in _sample(REFUND_CONFIRMED):
        order_id = record.expected_decision.tool_call.arguments.order_id
        assert re.match(ORDER_ID_PATTERN, order_id)
        assert order_id in record.messages[0].content


def test_order_id_is_not_always_at_the_same_position():
    """A single sentence skeleton would let the model learn a positional cue."""
    records = generate_family(REFUND_CONFIRMED, count=200, seed_base=5000)
    positions = {
        record.messages[0].content.index(
            record.expected_decision.tool_call.arguments.order_id
        )
        for record in records
    }
    assert len(positions) >= 4


# ---------------------------------------------------------------------------
# Tool-list helpers
# ---------------------------------------------------------------------------


def test_offer_tools_always_contains_the_required_tool():
    for seed in range(20):
        tools = offer_tools(random.Random(seed), required="get_order_status")
        assert "get_order_status" in tools
        assert set(tools) <= ALL_TOOL_NAMES
        assert len(set(tools)) == len(tools)


def test_offer_tools_respects_a_narrowed_pool():
    for seed in range(20):
        tools = offer_tools(
            random.Random(seed), "retrieval_tool", pool=KNOWLEDGE_TOOL_NAMES
        )
        assert set(tools) <= KNOWLEDGE_TOOL_NAMES
        assert "retrieval_tool" in tools


def test_offer_idle_tools_returns_a_non_empty_unique_list():
    for seed in range(20):
        tools = offer_idle_tools(random.Random(seed))
        assert tools
        assert set(tools) <= ALL_TOOL_NAMES
        assert len(set(tools)) == len(tools)
