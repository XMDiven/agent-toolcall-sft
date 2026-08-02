"""Run one model over a split under a fixed, recorded decoding configuration.

The baseline and the fine-tuned adapter must be generated the same way or the
difference between them is not attributable to training. Everything that could
change an output lives in `DECODING` and is written into the report, so a later
change is visible rather than silently invalidating the frozen baseline.
"""

import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from agent_toolcall_sft.data.records import DatasetRecord
from agent_toolcall_sft.evaluation.prompt import (
    PROMPT_VERSION,
    render_messages,
)

DECODING_VERSION = "v1"


@dataclass(frozen=True)
class Decoding:
    """Every knob that can change a generated token."""

    max_new_tokens: int = 256
    do_sample: bool = False
    num_beams: int = 1
    # Qwen3 emits a <think> block by default. Left on, it burns the token
    # budget before the JSON appears and the answer gets truncated.
    enable_thinking: bool = False


DECODING = Decoding()


@dataclass(frozen=True)
class Generation:
    """One raw model output plus what it cost."""

    record_id: str
    raw_output: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int


def load_model(
    model_id: str,
    revision: str | None = None,
    dtype: torch.dtype = torch.float16,
):
    """Load a causal LM onto the GPU in eval mode."""
    tokenizer = AutoTokenizer.from_pretrained(model_id, revision=revision)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, revision=revision, dtype=dtype, device_map="cuda"
    )
    model.eval()

    return model, tokenizer


def build_prompt(tokenizer, record: DatasetRecord) -> str:
    """Apply the template to the self-contained production JSON prompt."""
    return tokenizer.apply_chat_template(
        render_messages(record),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=DECODING.enable_thinking,
    )


@torch.inference_mode()
def generate_one(
    model,
    tokenizer,
    record: DatasetRecord,
    prompt_builder: Callable = build_prompt,
) -> Generation:
    """Generate one completion and time it."""
    prompt = prompt_builder(tokenizer, record)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    torch.cuda.synchronize()
    started = time.perf_counter()
    output = model.generate(
        **inputs,
        max_new_tokens=DECODING.max_new_tokens,
        do_sample=DECODING.do_sample,
        num_beams=DECODING.num_beams,
        pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
    )
    torch.cuda.synchronize()
    latency_ms = (time.perf_counter() - started) * 1000

    prompt_length = inputs["input_ids"].shape[-1]
    completion = output[0][prompt_length:]

    return Generation(
        record_id=record.id,
        raw_output=tokenizer.decode(completion, skip_special_tokens=True).strip(),
        latency_ms=round(latency_ms, 2),
        prompt_tokens=int(prompt_length),
        completion_tokens=int(completion.shape[-1]),
    )


def run_split(
    model,
    tokenizer,
    records: list[DatasetRecord],
    prompt_builder: Callable = build_prompt,
) -> list[Generation]:
    """Generate over every record, one at a time, in the given order."""
    torch.cuda.reset_peak_memory_stats()

    return [
        generate_one(model, tokenizer, record, prompt_builder=prompt_builder)
        for record in records
    ]


def stride_sample(records: list, limit: int) -> list:
    """Take a deterministic, evenly spaced smoke subset."""
    if limit >= len(records):
        return records
    step = len(records) / limit
    return [records[int(index * step)] for index in range(limit)]


def summarise_latency(latencies: list[float]) -> dict:
    ordered = sorted(latencies)
    return {
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2),
        "mean_ms": round(statistics.fmean(ordered), 2),
    }


def summarise_generations(generations: list[Generation]) -> dict:
    """Summarise performance without mixing it with behavior metrics."""
    return {
        "latency": summarise_latency([item.latency_ms for item in generations]),
        "tokens": {
            "prompt_mean": round(
                statistics.fmean(item.prompt_tokens for item in generations), 1
            ),
            "completion_mean": round(
                statistics.fmean(item.completion_tokens for item in generations), 1
            ),
        },
    }


def environment_fingerprint(
    model_id: str, prompt_version: str = PROMPT_VERSION
) -> dict:
    """Everything a reader needs to judge whether a rerun is comparable."""
    return {
        "model_id": model_id,
        "prompt_version": prompt_version,
        "decoding_version": DECODING_VERSION,
        "decoding": asdict(DECODING),
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
    }
