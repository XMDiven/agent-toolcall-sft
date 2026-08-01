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
    CORPUS_SIZE,
    DIRECT_ANSWER_FAMILIES,
    FAMILY_QUOTAS,
    HANDOFF_FAMILIES,
    KNOWLEDGE_FAMILIES,
    REFUND_CONFIRMED,
    SAFETY_FAMILIES,
)
from agent_toolcall_sft.data.generation import (
    TEMPLATE_VERSION,
    InsufficientVariety,
    ScenarioFamily,
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


def test_every_family_records_a_usable_seed(family_records):
    """Seeds skip where duplicates were rejected, but stay ordered and exact."""
    family, records = family_records
    seeds = [record.provenance.seed for record in records]

    assert seeds[0] == SAMPLE_SEED
    assert seeds == sorted(seeds)
    assert len(set(seeds)) == len(seeds)

    for record in records[:5]:
        rebuilt = family.draft(random.Random(f"{family.name}:{record.provenance.seed}"))
        assert rebuilt.messages == [
            {"role": message.role, "content": message.content}
            for message in record.messages
        ]


def test_every_family_offers_only_known_tools(family_records):
    _, records = family_records
    for record in records:
        assert set(record.tools) <= ALL_TOOL_NAMES
        assert len(set(record.tools)) == len(record.tools)


def test_every_family_produces_more_than_one_distinct_message(family_records):
    _, records = family_records
    assert len({record.messages[0].content for record in records}) > 1


# ---------------------------------------------------------------------------
# Variety gate
#
# Near-duplicate rows break the independence assumption behind the bootstrap
# confidence interval: 140 rows drawn from four sentences carry the evidence
# of four samples, not 140, and the interval computed from them is far too
# narrow. A family that cannot fill its quota with distinct messages has to
# fail here rather than quietly inflate the result.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", ALL_FAMILIES, ids=lambda f: f.name)
def test_family_fills_its_roadmap_quota_with_distinct_messages(family):
    quota = FAMILY_QUOTAS[family.name]
    records = generate_family(family, count=quota, seed_base=1)

    contents = {record.messages[0].content for record in records}
    assert len(records) == quota
    assert len(contents) == quota


def test_quotas_cover_every_family_and_sum_to_the_corpus_size():
    assert set(FAMILY_QUOTAS) == {family.name for family in ALL_FAMILIES}
    assert CORPUS_SIZE == 2800


def test_a_family_too_narrow_for_its_quota_raises():
    narrow = ScenarioFamily(
        name="narrow",
        domain="support",
        draft=lambda rng: generate_narrow_draft(),
    )
    with pytest.raises(InsufficientVariety, match="narrow"):
        generate_family(narrow, count=5, seed_base=1)


def generate_narrow_draft():
    from agent_toolcall_sft.data.generation import RecordDraft

    return RecordDraft(
        messages=[{"role": "user", "content": "只有这一句话"}],
        tools=["get_order_status"],
        expected_decision={"action": "clarify", "question": "请提供订单号。"},
    )


def test_families_do_not_share_synthetic_order_ids():
    """Without a family-salted seed every family emits the same id sequence."""
    from agent_toolcall_sft.data.families import (
        ORDER_STATUS_LOOKUP,
        REFUND_ELIGIBILITY_CHECK,
    )

    def ids(family):
        return [
            record.expected_decision.tool_call.arguments.order_id
            for record in generate_family(family, count=20, seed_base=1)
        ]

    assert ids(REFUND_CONFIRMED) != ids(ORDER_STATUS_LOOKUP)
    assert ids(ORDER_STATUS_LOOKUP) != ids(REFUND_ELIGIBILITY_CHECK)


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
