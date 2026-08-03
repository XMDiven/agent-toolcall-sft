"""The overfit probe needs a balanced, deterministic slice of the training set."""

from collections import Counter

import pytest

from agent_toolcall_sft.data.corpus import build_corpus, split_corpus
from agent_toolcall_sft.training.overfit import select_balanced, stratum_of


@pytest.fixture(scope="module")
def train_records():
    return split_corpus(build_corpus())["train"]


def test_every_present_stratum_is_represented(train_records):
    """knowledge holds only tool_call, so the 4x2 grid has five real cells."""
    population = {stratum_of(r) for r in train_records}
    sample = select_balanced(train_records, 64)

    assert len(sample) == 64
    assert {stratum_of(r) for r in sample} == population


def test_allocation_is_as_even_as_the_size_allows(train_records):
    counts = Counter(stratum_of(r) for r in select_balanced(train_records, 64))
    assert max(counts.values()) - min(counts.values()) <= 1


def test_selection_is_deterministic(train_records):
    first = [r.id for r in select_balanced(train_records, 64)]
    second = [r.id for r in select_balanced(train_records, 64)]
    assert first == second


def test_records_are_distinct(train_records):
    sample = select_balanced(train_records, 64)
    assert len({r.id for r in sample}) == 64


def test_size_below_the_stratum_count_is_refused(train_records):
    with pytest.raises(ValueError, match="at least"):
        select_balanced(train_records, 3)
