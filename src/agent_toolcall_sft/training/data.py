"""Assemble formatted records into padded training batches.

Padding carries `IGNORE_INDEX`, never a real target. Supervising pad tokens
would let a model lower its loss by predicting padding, which looks like
progress and teaches nothing.
"""

from agent_toolcall_sft.data.records import DatasetRecord
from agent_toolcall_sft.training.formatting import (
    IGNORE_INDEX,
    TrainingExample,
    format_record,
)


def build_examples(
    tokenizer,
    records: list[DatasetRecord],
    max_seq_length: int,
    limit: int | None = None,
) -> list[TrainingExample]:
    """Format records into examples, refusing any row with nothing to learn."""
    selected = records[:limit] if limit is not None else records

    examples = []
    for record in selected:
        example = format_record(tokenizer, record, max_seq_length)
        if all(label == IGNORE_INDEX for label in example.labels):
            raise ValueError(f"{record.id}: no supervised token")
        examples.append(example)

    return examples


def collate(batch: list[TrainingExample], pad_token_id: int) -> dict[str, list]:
    """Right-pad a batch to its longest row."""
    width = max(len(example.input_ids) for example in batch)

    return {
        "input_ids": [
            example.input_ids + [pad_token_id] * (width - len(example.input_ids))
            for example in batch
        ],
        "attention_mask": [
            [1] * len(example.input_ids) + [0] * (width - len(example.input_ids))
            for example in batch
        ],
        "labels": [
            example.labels + [IGNORE_INDEX] * (width - len(example.labels))
            for example in batch
        ],
    }
