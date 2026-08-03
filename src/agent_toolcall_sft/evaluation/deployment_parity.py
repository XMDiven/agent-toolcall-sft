"""Check that a deployment target reproduces the frozen evaluation outputs.

The reported metrics were measured on one machine. Serving on another only
inherits those numbers if the second machine produces the same decisions --
fp16 arithmetic differs between CUDA and Metal, and greedy decoding turns a
small logit difference into a different token whenever two candidates are
close.

This compares raw outputs record by record against a frozen run. It is a
measurement, not an assertion: a mismatch is reported, not hidden.
"""

import argparse
import json
import time
from pathlib import Path

from agent_toolcall_sft.data.records import DatasetRecord, read_records
from agent_toolcall_sft.evaluation.runner import DECODING, DECODING_VERSION
from agent_toolcall_sft.evaluation.scoring import is_fully_correct, score_record


def load_local_model(model_path: str, device: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.float16)
    model.to(device)
    model.eval()

    return model, tokenizer


def generate(model, tokenizer, record: DatasetRecord, device: str) -> tuple[str, float]:
    """Reproduce the frozen protocol exactly, on whatever device is given."""
    import torch

    from agent_toolcall_sft.evaluation.prompt import render_messages

    prompt = tokenizer.apply_chat_template(
        render_messages(record),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=DECODING.enable_thinking,
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(device)

    started = time.perf_counter()
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=DECODING.max_new_tokens,
            do_sample=DECODING.do_sample,
            num_beams=DECODING.num_beams,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    latency_ms = (time.perf_counter() - started) * 1000

    completion = output[0][inputs["input_ids"].shape[-1]:]

    return tokenizer.decode(completion, skip_special_tokens=True).strip(), latency_ms


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="merged model on this machine")
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="frozen run dir")
    parser.add_argument("--device", default="mps")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    reference = {
        row["record_id"]: row
        for row in (
            json.loads(line)
            for line in (args.reference / "predictions.jsonl").read_text().splitlines()
        )
    }
    records = read_records(args.split)
    if args.limit:
        records = records[: args.limit]

    model, tokenizer = load_local_model(args.model, args.device)

    rows, latencies = [], []
    for index, record in enumerate(records, 1):
        raw, latency_ms = generate(model, tokenizer, record, args.device)
        latencies.append(latency_ms)
        ref = reference[record.id]
        rows.append(
            {
                "record_id": record.id,
                "identical": raw == ref["raw_output"],
                "same_verdict": is_fully_correct(score_record(record, raw))
                == is_fully_correct(score_record(record, ref["raw_output"])),
                "local_output": raw,
                "reference_output": ref["raw_output"],
            }
        )
        if index % 50 == 0:
            print(f"  {index}/{len(records)}", flush=True)

    identical = sum(r["identical"] for r in rows)
    same_verdict = sum(r["same_verdict"] for r in rows)
    summary = {
        "records": len(rows),
        "identical_outputs": identical,
        "identical_rate": round(identical / len(rows), 4),
        "same_verdict": same_verdict,
        "same_verdict_rate": round(same_verdict / len(rows), 4),
        "device": args.device,
        "model": args.model,
        "reference": str(args.reference),
        "decoding_version": DECODING_VERSION,
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 2),
            "p50": round(sorted(latencies)[len(latencies) // 2], 2),
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95)], 2),
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
