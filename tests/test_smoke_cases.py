"""The fixed smoke cases must be stable and must exercise the knowledge-only menu."""

import pytest

from agent_toolcall_sft.data.corpus import build_corpus, split_corpus
from agent_toolcall_sft.training.smoke_cases import (
    KNOWLEDGE_TOOLS,
    is_knowledge_only,
    select_smoke_cases,
)


@pytest.fixture(scope="module")
def valid_records():
    return split_corpus(build_corpus())["valid"]


def test_size_and_knowledge_only_floor(valid_records):
    cases = select_smoke_cases(valid_records, size=20, knowledge_only=5)

    assert len(cases) == 20
    assert sum(is_knowledge_only(r) for r in cases) >= 5


def test_knowledge_only_means_no_support_tool(valid_records):
    for record in select_smoke_cases(valid_records, size=20, knowledge_only=5):
        if is_knowledge_only(record):
            assert set(record.tools) <= KNOWLEDGE_TOOLS


def test_selection_is_fixed(valid_records):
    first = [r.id for r in select_smoke_cases(valid_records, 20, 5)]
    second = [r.id for r in select_smoke_cases(valid_records, 20, 5)]

    assert first == second


def test_cases_are_distinct(valid_records):
    cases = select_smoke_cases(valid_records, 20, 5)
    assert len({r.id for r in cases}) == 20


def test_a_floor_above_the_case_count_is_refused(valid_records):
    with pytest.raises(ValueError, match="exceeds the case count"):
        select_smoke_cases(valid_records, size=20, knowledge_only=21)


def test_cases_span_several_families(valid_records):
    """Twenty rows of one family reproduce just as well and probe far less."""
    cases = select_smoke_cases(valid_records, 20, 5)
    assert len({r.scenario_family for r in cases}) >= 8
