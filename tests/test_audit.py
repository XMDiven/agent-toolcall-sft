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


def test_sample_has_a_canonical_deterministic_order(sample):
    assert sample == sorted(sample, key=lambda record: (stratum_of(record), record.id))


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


def test_sample_covers_every_population_safety_tag(auditable, sample):
    population_tags = {tag for record in auditable for tag in record.safety_tags}
    sample_tags = {tag for record in sample for tag in record.safety_tags}

    assert sample_tags == population_tags


def test_sample_supplements_all_tags_from_one_planted_record(auditable, sample):
    sampled_ids = {record.id for record in sample}
    sampled_templates = {record.template_key for record in sample}
    candidate = next(
        record
        for record in auditable
        if record.id not in sampled_ids
        and record.template_key not in sampled_templates
        and "high_risk" not in record.safety_tags
    )
    planted = list(auditable)
    index = planted.index(candidate)
    planted[index] = candidate.model_copy(
        update={
            "safety_tags": [
                *candidate.safety_tags,
                "rare_planted_tag_a",
                "rare_planted_tag_b",
            ]
        }
    )

    supplemented = sample_for_audit(planted)

    sampled_tags = {tag for record in supplemented for tag in record.safety_tags}
    assert {"rare_planted_tag_a", "rare_planted_tag_b"} <= sampled_tags
    assert len(supplemented) == AUDIT_SIZE
    assert len({record.template_key for record in supplemented}) == AUDIT_SIZE
    assert {record.domain for record in supplemented} == {"knowledge", "support"}
    assert {record.expected_action for record in supplemented} == {
        "tool_call",
        "clarify",
        "direct_answer",
        "handoff",
    }
    counts = Counter(stratum_of(record) for record in supplemented)
    assert counts["safety"] >= 15
    assert counts["knowledge"] >= 15


def test_supplementing_a_tag_preserves_the_complete_stratum_mix(auditable, sample):
    sampled_ids = {record.id for record in sample}
    sampled_templates = {record.template_key for record in sample}
    candidate = next(
        record
        for record in auditable
        if record.id not in sampled_ids
        and record.template_key not in sampled_templates
        and stratum_of(record) == "support:tool_call"
    )
    planted = list(auditable)
    planted[planted.index(candidate)] = candidate.model_copy(
        update={"safety_tags": [*candidate.safety_tags, "rare_stratum_tag"]}
    )

    supplemented = sample_for_audit(planted)

    assert Counter(map(stratum_of, supplemented)) == Counter(map(stratum_of, sample))


def test_tag_supplementation_backtracks_when_the_first_candidate_blocks_a_tag(
    auditable, sample
):
    sampled_ids = {record.id for record in sample}
    sampled_templates = {record.template_key for record in sample}
    by_stratum_and_template = {}
    for record in auditable:
        if record.id in sampled_ids or record.template_key in sampled_templates:
            continue
        by_stratum_and_template.setdefault(
            (stratum_of(record), record.template_key), []
        ).append(record)

    shared_template_key = next(
        key
        for key, records in sorted(by_stratum_and_template.items())
        if len(records) >= 2
        and any(
            other_stratum == key[0] and other_template > key[1]
            for other_stratum, other_template in by_stratum_and_template
        )
    )
    stratum, blocked_template = shared_template_key
    first_candidate, only_later_candidate = sorted(
        by_stratum_and_template[shared_template_key], key=lambda record: record.id
    )[:2]
    alternate = next(
        by_stratum_and_template[(other_stratum, other_template)][0]
        for other_stratum, other_template in sorted(by_stratum_and_template)
        if other_stratum == stratum and other_template > blocked_template
    )

    planted = list(auditable)

    def add_tags(record, *tags):
        index = planted.index(record)
        planted[index] = record.model_copy(
            update={"safety_tags": [*record.safety_tags, *tags]}
        )

    add_tags(first_candidate, "rare_early_tag")
    add_tags(alternate, "rare_early_tag")
    add_tags(only_later_candidate, "rare_later_tag")

    supplemented = sample_for_audit(planted)
    supplemented_tags = {
        tag for record in supplemented for tag in record.safety_tags
    }

    assert {"rare_early_tag", "rare_later_tag"} <= supplemented_tags
    assert alternate.id in {record.id for record in supplemented}
    assert only_later_candidate.id in {record.id for record in supplemented}
    assert Counter(map(stratum_of, supplemented)) == Counter(map(stratum_of, sample))


def test_sample_never_touches_the_test_split(sample):
    test_ids = {record.id for record in split_corpus(build_corpus())["test"]}
    assert not {record.id for record in sample} & test_ids


def test_sheet_lists_every_sampled_record(sample):
    sheet = render_audit_sheet(sample)
    for record in sample:
        assert record.id in sheet
    assert sheet.count("- [ ] 通过") == len(sample)


def test_sample_prefers_distinct_templates(sample):
    """Two rows from one template teach an auditor nothing the first did not."""
    keys = [record.template_key for record in sample]
    assert len(set(keys)) == len(keys)
