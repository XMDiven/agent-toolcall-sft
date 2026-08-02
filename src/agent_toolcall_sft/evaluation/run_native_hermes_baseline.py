"""Freeze the native Hermes auxiliary baseline on gold tool-call records."""

import argparse
from pathlib import Path

from agent_toolcall_sft.evaluation.evidence import execute_frozen_run
from agent_toolcall_sft.evaluation.native_hermes import (
    NATIVE_HERMES_PROMPT_VERSION,
    NATIVE_SELECTION_RULE,
    build_native_prompt,
    select_native_records,
)
from agent_toolcall_sft.evaluation.scoring import (
    RecordScore,
    native_auxiliary_metrics,
    schema_error_taxonomy,
)

DEFAULT_MODEL = "Qwen/Qwen3-1.7B"
DEFAULT_SPLIT = Path("data/processed/test.jsonl")
DEFAULT_MANIFEST = Path("data/manifests/split_v2.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=None, help="smoke subset after selection")
    parser.add_argument("--tag", default="native-hermes-v1")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    return parser


def build_native_summary(
    *,
    split: str,
    source_records: int,
    selected_records: int,
    evaluated_records: int,
    scores: list[RecordScore],
    performance: dict,
) -> dict:
    return {
        "protocol": "native_hermes_auxiliary",
        "prompt_version": NATIVE_HERMES_PROMPT_VERSION,
        "selection_rule": NATIVE_SELECTION_RULE,
        "split": split,
        "source_records": source_records,
        "selected_records": selected_records,
        "evaluated_records": evaluated_records,
        **performance,
        "auxiliary_metrics": native_auxiliary_metrics(scores),
        "schema_errors": schema_error_taxonomy(scores),
    }


def execute(args) -> Path:
    return execute_frozen_run(
        args,
        selector=select_native_records,
        prompt_builder=build_native_prompt,
        prompt_version=NATIVE_HERMES_PROMPT_VERSION,
        summary_builder=build_native_summary,
    )


def main() -> None:
    execute(build_parser().parse_args())


if __name__ == "__main__":
    main()
