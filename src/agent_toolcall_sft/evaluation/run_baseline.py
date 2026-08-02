"""Freeze the full-split production JSON baseline without overwriting evidence."""

import argparse
from pathlib import Path

from agent_toolcall_sft.data.records import DatasetRecord
from agent_toolcall_sft.evaluation.evidence import execute_frozen_run
from agent_toolcall_sft.evaluation.prompt import PROMPT_VERSION
from agent_toolcall_sft.evaluation.runner import build_prompt
from agent_toolcall_sft.evaluation.scoring import (
    RecordScore,
    aggregate_by_domain,
    confusion,
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
    parser.add_argument("--limit", type=int, default=None, help="smoke-test subset")
    parser.add_argument("--tag", default="production-json-v2")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    return parser


def select_production_records(
    records: list[DatasetRecord],
) -> list[DatasetRecord]:
    return records


def build_production_summary(
    *,
    split: str,
    source_records: int,
    selected_records: int,
    evaluated_records: int,
    scores: list[RecordScore],
    performance: dict,
) -> dict:
    return {
        "protocol": "production_json",
        "prompt_version": PROMPT_VERSION,
        "selection_rule": "all test records; --limit is smoke-only",
        "split": split,
        "source_records": source_records,
        "selected_records": selected_records,
        "evaluated_records": evaluated_records,
        "records": evaluated_records,
        **performance,
        "metrics": aggregate_by_domain(scores),
        "confusion": confusion(scores),
        "schema_errors": schema_error_taxonomy(scores),
    }


def execute(args) -> Path:
    return execute_frozen_run(
        args,
        selector=select_production_records,
        prompt_builder=build_prompt,
        prompt_version=PROMPT_VERSION,
        summary_builder=build_production_summary,
    )


def main() -> None:
    execute(build_parser().parse_args())


if __name__ == "__main__":
    main()
