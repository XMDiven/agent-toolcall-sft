"""Run one model over a split under a fixed, recorded decoding configuration.

The baseline and the fine-tuned adapter must be generated the same way or the
difference between them is not attributable to training. Everything that could
change an output lives in `DECODING` and is written into the report, so a later
change is visible rather than silently invalidating the frozen baseline.
"""

import time
from dataclasses import asdict, dataclass

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from agent_toolcall_sft.data.records import DatasetRecord
from agent_toolcall_sft.evaluation.prompt import (
    PROMPT_VERSION,
    build_tool_specs,
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


def load_model(model_id: str, dtype: torch.dtype = torch.float16):
    """Load a causal LM onto the GPU in eval mode."""
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, dtype=dtype, device_map="cuda"
    )
    model.eval()

    return model, tokenizer


def build_prompt(tokenizer, record: DatasetRecord) -> str:
    """Apply the model's chat template, handing it the tools natively.

    Passing `tools=` lets Qwen3 render its own <tools> block, so the base
    model is asked for output in the format it was trained to produce.
    """
    return tokenizer.apply_chat_template(
        render_messages(record),
        tools=build_tool_specs(record.tools),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=DECODING.enable_thinking,
    )


@torch.inference_mode()
def generate_one(model, tokenizer, record: DatasetRecord) -> Generation:
    """Generate one completion and time it."""
    prompt = build_prompt(tokenizer, record)
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


def run_split(model, tokenizer, records: list[DatasetRecord]) -> list[Generation]:
    """Generate over every record, one at a time, in the given order."""
    torch.cuda.reset_peak_memory_stats()

    return [generate_one(model, tokenizer, record) for record in records]


def environment_fingerprint(model_id: str) -> dict:
    """Everything a reader needs to judge whether a rerun is comparable."""
    return {
        "model_id": model_id,
        "prompt_version": PROMPT_VERSION,
        "decoding_version": DECODING_VERSION,
        "decoding": asdict(DECODING),
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
    }
