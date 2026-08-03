"""Score an adapter on a record slice with the frozen evaluation pipeline.

This reuses `score_record` and `aggregate_by_domain` rather than re-deriving
accuracy, so an overfit probe and the baseline are judged by the same rules.
It is a diagnostic entry point: it writes no frozen evidence and must not be
used to produce comparison numbers.
"""

import argparse
import json
from pathlib import Path

from agent_toolcall_sft.data.records import read_records
from agent_toolcall_sft.evaluation.runner import load_model, run_split
from agent_toolcall_sft.evaluation.scoring import aggregate_by_domain, score_record


def load_adapter_model(base_model: str, adapter: str):
    """Load the base weights and apply a trained LoRA adapter."""
    from peft import PeftModel

    model, tokenizer = load_model(base_model)
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()

    return model, tokenizer


def score_slice(model, tokenizer, records) -> dict:
    generations = run_split(model, tokenizer, records)
    scores = [
        score_record(record, generation.raw_output)
        for record, generation in zip(records, generations)
    ]

    return {
        "records": len(records),
        "metrics": aggregate_by_domain(scores),
        "samples": [
            {"id": r.id, "raw_output": g.raw_output}
            for r, g in list(zip(records, generations))[:3]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter", default=None, help="omit to score the base model")
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.adapter:
        model, tokenizer = load_adapter_model(args.base_model, args.adapter)
    else:
        model, tokenizer = load_model(args.base_model)

    report = score_slice(model, tokenizer, read_records(args.split))
    report["adapter"] = args.adapter
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
