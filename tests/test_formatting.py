"""Training examples must supervise the assistant span only, and nothing else."""

import json
from pathlib import Path

import pytest

from agent_toolcall_sft.contracts import parse_decision
from agent_toolcall_sft.data.corpus import build_corpus, split_corpus
from agent_toolcall_sft.training.formatting import (
    IGNORE_INDEX,
    build_target_text,
    format_record,
)

REAL_MODEL = Path("/home/mdiven/models/Qwen3-1.7B")


class FakeTokenizer:
    """Deterministic stand-in: one token per character, plus a marked EOS."""

    eos_token = "<eos>"
    eos_token_id = 0

    def apply_chat_template(self, messages, add_generation_prompt=False, tokenize=False, **kw):
        text = "|".join(f"{m['role']}:{m['content']}" for m in messages)
        if add_generation_prompt:
            text += "|assistant:"
        return text if not tokenize else self(text)["input_ids"]

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": [ord(c) for c in text]}


@pytest.fixture(scope="module")
def records():
    splits = split_corpus(build_corpus())
    return splits["train"]


def test_target_text_round_trips_through_the_evaluation_parser(records):
    """What we train on must be exactly what the evaluator accepts."""
    for record in records[:200]:
        decision = parse_decision(json.loads(build_target_text(record)))
        assert decision == record.expected_decision


def test_prompt_tokens_are_masked_and_answer_tokens_are_not(records):
    tokenizer = FakeTokenizer()
    example = format_record(tokenizer, records[0], max_seq_length=4096)

    assert len(example.input_ids) == len(example.labels)
    supervised = [i for i, label in enumerate(example.labels) if label != IGNORE_INDEX]
    assert supervised, "no supervised token"

    # The supervised region is a single suffix, never a hole in the middle.
    assert supervised == list(range(supervised[0], len(example.labels)))
    assert all(label == IGNORE_INDEX for label in example.labels[: supervised[0]])
    assert example.labels[supervised[0]:] == example.input_ids[supervised[0]:]


def test_supervised_span_decodes_back_to_the_gold_decision(records):
    tokenizer = FakeTokenizer()
    record = records[0]
    example = format_record(tokenizer, record, max_seq_length=4096)

    supervised = [t for t, label in zip(example.input_ids, example.labels) if label != IGNORE_INDEX]
    text = "".join(chr(t) for t in supervised).removesuffix(tokenizer.eos_token)
    assert parse_decision(json.loads(text)) == record.expected_decision


def test_offered_tools_are_rendered_and_vary_between_records(records):
    tokenizer = FakeTokenizer()
    by_tools = {}
    for record in records:
        by_tools.setdefault(tuple(sorted(record.tools)), record)
        if len(by_tools) >= 3:
            break

    prompts = []
    for record in by_tools.values():
        example = format_record(tokenizer, record, max_seq_length=4096)
        prompt = "".join(
            chr(t) for t, label in zip(example.input_ids, example.labels)
            if label == IGNORE_INDEX
        )
        for name in record.tools:
            assert name in prompt, f"{name} missing from prompt of {record.id}"
        prompts.append(prompt)

    assert len(set(prompts)) == len(prompts), "tool menus did not vary across records"


def test_truncation_never_drops_the_whole_answer(records):
    tokenizer = FakeTokenizer()
    with pytest.raises(ValueError):
        format_record(tokenizer, records[0], max_seq_length=8)


@pytest.mark.skipif(not REAL_MODEL.exists(), reason="base weights not present")
def test_real_chat_template_masks_only_the_answer(records):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(REAL_MODEL))
    example = format_record(tokenizer, records[0], max_seq_length=1024)

    supervised = [t for t, label in zip(example.input_ids, example.labels) if label != IGNORE_INDEX]
    decoded = tokenizer.decode(supervised, skip_special_tokens=True)
    assert parse_decision(json.loads(decoded)) == records[0].expected_decision
