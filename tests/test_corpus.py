import hashlib
import json

import pytest

from agent_toolcall_sft.contracts import HandoffDecision
from agent_toolcall_sft.data import corpus as corpus_module
from agent_toolcall_sft.data.corpus import (
    SPLIT_SIZES,
    build_corpus,
    build_manifest,
    find_near_duplicates,
    leakage_report,
    normalize,
    split_corpus,
    write_split,
)
from agent_toolcall_sft.data.families import CORPUS_SIZE, FAMILY_QUOTAS
from agent_toolcall_sft.data.records import read_records


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture(scope="module")
def splits(corpus):
    return split_corpus(corpus)


@pytest.fixture(scope="module")
def report(splits):
    return leakage_report(splits)


# ---------------------------------------------------------------------------
# Corpus shape
# ---------------------------------------------------------------------------


def test_corpus_matches_the_roadmap_quotas(corpus):
    assert len(corpus) == CORPUS_SIZE == 2800
    counts = {}
    for record in corpus:
        counts[record.scenario_family] = counts.get(record.scenario_family, 0) + 1
    assert counts == FAMILY_QUOTAS


def test_corpus_is_reproducible():
    assert build_corpus() == build_corpus()


def test_corpus_messages_are_all_distinct(corpus):
    assert len({record.messages[0].content for record in corpus}) == len(corpus)


# ---------------------------------------------------------------------------
# Split shape
# ---------------------------------------------------------------------------


def test_splits_hit_the_exact_target_sizes(splits):
    assert {name: len(records) for name, records in splits.items()} == SPLIT_SIZES


def test_splits_partition_the_corpus(corpus, splits):
    ids = [record.id for records in splits.values() for record in records]
    assert len(ids) == len(corpus)
    assert set(ids) == {record.id for record in corpus}


def test_split_is_reproducible(corpus, splits):
    again = split_corpus(corpus)
    for name, records in splits.items():
        assert [r.id for r in again[name]] == [r.id for r in records]


def test_every_split_covers_both_domains_and_all_actions(splits):
    for records in splits.values():
        assert {r.domain for r in records} == {"knowledge", "support"}
        assert {r.expected_action for r in records} == {
            "tool_call",
            "clarify",
            "direct_answer",
            "handoff",
        }


def test_test_split_holds_enough_of_each_domain(splits):
    """Both stratified subsets must stay large enough to report a CI at all.

    The floor is 100, not 150: knowledge is 20% of the corpus, so a 500-row
    test split cannot hold more than about 100 of it without distorting the
    mix the headline number is measured on. See the note under ROADMAP 1.3.
    """
    counts = {"knowledge": 0, "support": 0}
    for record in splits["test"]:
        counts[record.domain] += 1

    assert counts["knowledge"] >= 100
    assert counts["support"] >= 100


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------


def test_no_template_key_spans_two_splits(report):
    assert report["shared_template_keys"] == {
        pair: [] for pair in report["shared_template_keys"]
    }


def test_no_identical_content_across_splits(report):
    assert set(report["shared_content_hashes"].values()) == {0}


def test_no_content_matches_after_normalisation(report):
    assert set(report["shared_normalized_hashes"].values()) == {0}


def test_no_near_duplicates_across_splits(report):
    assert report["near_duplicate_pairs"] == []


def test_normalisation_folds_cosmetic_differences():
    assert normalize("你好，退货政策是什么？") == normalize("你好 退货政策是什么")
    assert normalize("ORD-100001") == normalize("ord 100001")


def test_near_duplicate_sweep_catches_a_planted_pair(corpus):
    """A rewrapped sentence must be reported, or the sweep proves nothing."""
    train = [r for r in corpus if r.scenario_family == "kb_lookup"][:5]
    planted = train[0].model_copy(
        update={"id": "planted_000000", "messages": train[0].messages}
    )

    matches = find_near_duplicates({"train": train, "test": [planted]})
    assert matches
    assert matches[0][2] >= 0.85


def test_parameterized_hash_catches_order_ids_across_splits(corpus):
    left = corpus[0].model_copy(
        update={
            "id": "parameterized_left",
            "template_key": "parameterized:left",
            "messages": [
                corpus[0].messages[0].model_copy(
                    update={"content": "查询订单 ORD-123456"}
                )
            ],
        }
    )
    right = corpus[0].model_copy(
        update={
            "id": "parameterized_right",
            "template_key": "parameterized:right",
            "messages": [
                corpus[0].messages[0].model_copy(
                    update={"content": "查询订单 ORD-654321"}
                )
            ],
        }
    )
    planted = {"left": [left], "right": [right]}

    report = leakage_report(planted)

    assert corpus_module.normalize_synthetic_parameters("ORD-123456") == "ORD-NNNNNN"
    assert report["shared_parameterized_hashes"] == {"left|right": 1}
    assert build_manifest(planted, seed=1)["leakage_clean"] is False


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_declares_the_split_clean(splits):
    manifest = build_manifest(splits, seed=1)
    assert manifest["leakage_clean"] is True
    assert manifest["split_unit"] == "template_key"
    assert manifest["total_records"] == 2800
    assert set(manifest["splits"]) == set(SPLIT_SIZES)


def test_manifest_records_each_split_hash_and_mix(splits):
    manifest = build_manifest(splits, seed=1)
    for name, size in SPLIT_SIZES.items():
        summary = manifest["splits"][name]
        assert summary["count"] == size
        assert len(summary["sha256"]) == 64
        assert sum(summary["by_domain"].values()) == size
        assert sum(summary["by_action"].values()) == size


def test_written_splits_round_trip(tmp_path, splits):
    manifest = build_manifest(splits, seed=1)
    written = write_split(tmp_path, splits, manifest)

    for name, size in SPLIT_SIZES.items():
        reloaded = read_records(written[name])
        assert len(reloaded) == size
        assert reloaded == splits[name]

    assert written["manifest"].exists()


# ---------------------------------------------------------------------------
# Regression guards for the review findings
# ---------------------------------------------------------------------------


def test_no_core_sentence_pattern_crosses_a_split(splits):
    """Randomised order ids must not disguise a shared skeleton.

    order_status_lookup once left template_key unset, so every record became
    its own group and 30 skeletons -- 90 records -- straddled the boundary
    while the manifest still reported leakage_clean.
    """
    import re

    order_id = re.compile(r"ORD-\d{6}")
    patterns = {
        name: {order_id.sub("<ORD>", r.messages[0].content) for r in records}
        for name, records in splits.items()
    }

    assert not patterns["train"] & patterns["test"]
    assert not patterns["train"] & patterns["valid"]
    assert not patterns["valid"] & patterns["test"]


def test_manifest_hash_uses_compact_canonical_json(splits):
    from agent_toolcall_sft.data.corpus import _split_summary

    records = splits["test"][:2]
    payload = "\n".join(
        json.dumps(
            record.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for record in records
    )

    assert _split_summary(records)["sha256"] == hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def test_manifest_hash_covers_every_frozen_record_field(splits):
    """Every semantically relevant record field belongs to the fingerprint."""
    from agent_toolcall_sft.data.corpus import _split_summary

    records = splits["test"]
    before = _split_summary(records)["sha256"]

    mutations = (
        {"tools": [*records[0].tools, "create_support_ticket"]},
        {"tools": list(reversed(records[0].tools))},
        {"expected_action": "handoff"},
        {"expected_decision": HandoffDecision(action="handoff", reason="tampered")},
        {"safety_tags": [*records[0].safety_tags, "tampered"]},
        {
            "provenance": records[0].provenance.model_copy(
                update={"seed": records[0].provenance.seed + 1}
            )
        },
    )

    for mutation in mutations:
        tampered = list(records)
        tampered[0] = records[0].model_copy(update=mutation)
        assert _split_summary(tampered)["sha256"] != before
