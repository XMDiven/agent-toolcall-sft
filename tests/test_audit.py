from collections import Counter

import pytest

from agent_toolcall_sft.data.audit import (
    AUDIT_SIZE,
    render_audit_sheet,
    sample_for_audit,
    stratum_of,
)
from agent_toolcall_sft.data.corpus import build_corpus, split_corpus


@pytest.fixture(scope="module")
def auditable():
    """Everything an auditor is allowed to read: train and valid, never test."""
    splits = split_corpus(build_corpus())
    return splits["train"] + splits["valid"]


@pytest.fixture(scope="module")
def sample(auditable):
    return sample_for_audit(auditable)


def test_sample_has_the_requested_size(sample):
    assert len(sample) == AUDIT_SIZE


def test_sample_is_reproducible(auditable, sample):
    assert [r.id for r in sample_for_audit(auditable)] == [r.id for r in sample]


def test_sample_holds_no_duplicates(sample):
    assert len({record.id for record in sample}) == len(sample)


def test_safety_and_knowledge_strata_meet_the_roadmap_floors(sample):
    counts = Counter(stratum_of(record) for record in sample)
    assert counts["safety"] >= 15
    assert counts["knowledge"] >= 15


def test_sample_covers_every_action(sample):
    assert {record.expected_action for record in sample} == {
        "tool_call",
        "clarify",
        "direct_answer",
        "handoff",
    }


def test_sample_never_touches_the_test_split(sample):
    test_ids = {record.id for record in split_corpus(build_corpus())["test"]}
    assert not {record.id for record in sample} & test_ids


def test_sheet_lists_every_sampled_record(sample):
    sheet = render_audit_sheet(sample)
    for record in sample:
        assert record.id in sheet
    assert sheet.count("- [ ] 通过") == len(sample)
