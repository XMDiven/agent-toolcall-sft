"""Freeze a baseline: run one model over the test split and write the evidence.

Usage:
    uv run python -m agent_toolcall_sft.evaluation.run_baseline --limit 10
    uv run python -m agent_toolcall_sft.evaluation.run_baseline

Per-sample predictions land under `artifacts/` (git-ignored). The summary is
JSON so the report can quote it without anyone retyping a number.
"""

import argparse
import json
import statistics
from dataclasses import asdict
from pathlib import Path

from agent_toolcall_sft.data.records import read_records
from agent_toolcall_sft.evaluation.runner import (
    environment_fingerprint,
    load_model,
    run_split,
)
from agent_toolcall_sft.evaluation.scoring import (
    aggregate_by_domain,
    confusion,
    score_record,
)

DEFAULT_MODEL = "Qwen/Qwen3-1.7B"
DEFAULT_SPLIT = Path("data/processed/test.jsonl")


def summarise_latency(latencies: list[float]) -> dict:
    ordered = sorted(latencies)
    return {
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2),
        "mean_ms": round(statistics.fmean(ordered), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--limit", type=int, default=None, help="smoke-test subset")
    parser.add_argument("--tag", default="baseline")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args()

    records = read_records(args.split)
    if args.limit:
        records = records[: args.limit]
    print(f"loaded {len(records)} records from {args.split}")

    model, tokenizer = load_model(args.model)
    print(f"loaded {args.model}")

    generations = run_split(model, tokenizer, records)
    scores = [
        score_record(record, generation.raw_output)
        for record, generation in zip(records, generations, strict=True)
    ]

    destination = args.output_dir / args.tag
    destination.mkdir(parents=True, exist_ok=True)

    with (destination / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for record, generation, score in zip(
            records, generations, scores, strict=True
        ):
            handle.write(
                json.dumps(
                    {
                        "record_id": record.id,
                        "scenario_family": record.scenario_family,
                        "tools": record.tools,
                        "user": record.messages[-1].content,
                        "expected": record.expected_decision.model_dump(),
                        "raw_output": generation.raw_output,
                        "latency_ms": generation.latency_ms,
                        "score": asdict(score),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    summary = {
        "split": str(args.split),
        "records": len(records),
        "environment": environment_fingerprint(args.model),
        "latency": summarise_latency([g.latency_ms for g in generations]),
        "tokens": {
            "prompt_mean": round(
                statistics.fmean(g.prompt_tokens for g in generations), 1
            ),
            "completion_mean": round(
                statistics.fmean(g.completion_tokens for g in generations), 1
            ),
        },
        "metrics": aggregate_by_domain(scores),
        "confusion": confusion(scores),
    }
    (destination / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary["metrics"]["overall"], ensure_ascii=False, indent=2))
    print(f"\nwrote {destination}/predictions.jsonl and summary.json")


if __name__ == "__main__":
    main()
