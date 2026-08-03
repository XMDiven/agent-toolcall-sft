"""Turn dataset records into supervised training examples.

Two invariants make or break the whole comparison:

Loss is computed on the assistant answer only. The prompt carries the tool
contracts and the four-decision instructions -- supervising those would teach
the model to recite its own instructions, and the loss would still fall.

The prompt is byte-for-byte the one the frozen baseline used. Training on a
different rendering than the evaluation asks would make the paired comparison
measure the prompt change rather than the fine-tuning.

Masking works by construction: the prompt and the answer are encoded
separately and the boundary is their token count, so it never depends on
guessing where a chat template placed its markers.
"""

import json
from dataclasses import dataclass

from agent_toolcall_sft.data.records import DatasetRecord
from agent_toolcall_sft.evaluation.prompt import render_messages

IGNORE_INDEX = -100


@dataclass(frozen=True)
class TrainingExample:
    input_ids: list[int]
    labels: list[int]


def build_target_text(record: DatasetRecord) -> str:
    """Serialise the gold decision exactly as the production protocol expects."""
    return json.dumps(
        record.expected_decision.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _token_ids(encoded) -> list[int]:
    """Normalise what a tokenizer returns into a flat list of ids.

    `apply_chat_template(tokenize=True)` yields a BatchEncoding on current
    transformers; iterating it directly gives the dict keys, which silently
    replaces a 449-token prompt with two strings.
    """
    ids = encoded["input_ids"] if hasattr(encoded, "keys") else encoded
    if ids and isinstance(ids[0], (list, tuple)):
        ids = ids[0]
    ids = list(ids)
    if not all(isinstance(token, int) for token in ids):
        raise TypeError(f"tokenizer returned non-integer ids: {ids[:4]}")

    return ids


def format_record(
    tokenizer, record: DatasetRecord, max_seq_length: int
) -> TrainingExample:
    """Build one example whose labels cover the assistant answer only."""
    prompt_ids = _token_ids(
        tokenizer.apply_chat_template(
            render_messages(record), add_generation_prompt=True, tokenize=True
        )
    )
    answer = build_target_text(record) + (tokenizer.eos_token or "")
    answer_ids = _token_ids(tokenizer(answer, add_special_tokens=False))

    if len(prompt_ids) + len(answer_ids) > max_seq_length:
        # Truncating the answer would supervise a broken JSON fragment, so the
        # prompt gives way first -- and if even that is not enough, refuse.
        budget = max_seq_length - len(answer_ids)
        if budget <= 0:
            raise ValueError(
                f"{record.id}: answer needs {len(answer_ids)} tokens but "
                f"max_seq_length is {max_seq_length}"
            )
        prompt_ids = prompt_ids[-budget:]

    return TrainingExample(
        input_ids=list(prompt_ids) + list(answer_ids),
        labels=[IGNORE_INDEX] * len(prompt_ids) + list(answer_ids),
    )
