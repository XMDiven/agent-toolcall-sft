"""Freeze the fine-tuned adapter on the same protocol the baseline used.

Every coordinate that could shift a number is held to the baseline's value --
the same 500 records, the same production JSON prompt, the same greedy
decoding. The only intended difference is the adapter, so the paired
difference is attributable to it.
"""

import argparse
from pathlib import Path

from agent_toolcall_sft.evaluation.evidence import execute_frozen_run, positive_int
from agent_toolcall_sft.evaluation.prompt import PROMPT_VERSION
from agent_toolcall_sft.evaluation.run_baseline import (
    build_production_summary,
    select_production_records,
)
from agent_toolcall_sft.evaluation.runner import build_prompt, load_model

DEFAULT_SPLIT = Path("data/processed/test.jsonl")
DEFAULT_MANIFEST = Path("data/manifests/split_v2.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="base weights")
    parser.add_argument("--adapter", required=True, help="trained LoRA adapter")
    parser.add_argument("--revision")
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=positive_int, default=None, help="smoke only")
    parser.add_argument("--tag", default="adapter-production-json-v1")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))

    return parser


def load_base_with_adapter(args):
    from peft import PeftModel

    model, tokenizer = load_model(args.model, revision=args.revision)
    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    return model, tokenizer


def execute(args) -> Path:
    return execute_frozen_run(
        args,
        selector=select_production_records,
        prompt_builder=build_prompt,
        prompt_version=PROMPT_VERSION,
        summary_builder=build_production_summary,
        model_loader=load_base_with_adapter,
    )


def main() -> None:
    execute(build_parser().parse_args())


if __name__ == "__main__":
    main()
