"""Batching must pad without ever inventing supervision."""

import pytest
from test_formatting import FakeTokenizer

from agent_toolcall_sft.data.corpus import build_corpus, split_corpus
from agent_toolcall_sft.training.data import build_examples, collate
from agent_toolcall_sft.training.formatting import IGNORE_INDEX, TrainingExample

PAD = 7


@pytest.fixture(scope="module")
def records():
    return split_corpus(build_corpus())["train"][:40]


def test_build_examples_limits_and_supervises_every_row(records):
    examples = build_examples(FakeTokenizer(), records, max_seq_length=4096, limit=10)

    assert len(examples) == 10
    for example in examples:
        assert any(label != IGNORE_INDEX for label in example.labels)


def test_build_examples_rejects_an_unsupervised_row():
    class EmptyAnswerTokenizer(FakeTokenizer):
        def __call__(self, text, add_special_tokens=False):
            return {"input_ids": []}

    records = split_corpus(build_corpus())["train"][:1]
    with pytest.raises(ValueError, match="no supervised token"):
        build_examples(EmptyAnswerTokenizer(), records, max_seq_length=4096)


def test_collate_pads_inputs_and_masks_the_padding():
    batch = [
        TrainingExample(input_ids=[1, 2, 3], labels=[IGNORE_INDEX, 2, 3]),
        TrainingExample(input_ids=[4, 5], labels=[IGNORE_INDEX, 5]),
    ]
    out = collate(batch, pad_token_id=PAD)

    assert out["input_ids"] == [[1, 2, 3], [4, 5, PAD]]
    assert out["attention_mask"] == [[1, 1, 1], [1, 1, 0]]
    assert out["labels"] == [[IGNORE_INDEX, 2, 3], [IGNORE_INDEX, 5, IGNORE_INDEX]]


def test_padding_is_never_supervised():
    batch = [
        TrainingExample(input_ids=[1], labels=[1]),
        TrainingExample(input_ids=[1, 2, 3, 4], labels=[IGNORE_INDEX] * 3 + [4]),
    ]
    out = collate(batch, pad_token_id=PAD)

    for ids, labels, mask in zip(out["input_ids"], out["labels"], out["attention_mask"]):
        for token, label, attend in zip(ids, labels, mask):
            if attend == 0:
                assert label == IGNORE_INDEX, "padding must not carry a target"
                assert token == PAD
