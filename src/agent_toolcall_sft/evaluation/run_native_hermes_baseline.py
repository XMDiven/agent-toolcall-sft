"""Freeze the native Hermes auxiliary baseline on gold tool-call records."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agent_toolcall_sft.data.records import read_records
from agent_toolcall_sft.evaluation.evidence import (
    build_prediction_rows,
    build_run_metadata,
    reserve_destination,
    verify_manifest_records,
    write_frozen_evidence,
)
from agent_toolcall_sft.evaluation.native_hermes import (
    NATIVE_HERMES_PROMPT_VERSION,
    NATIVE_SELECTION_RULE,
    build_native_prompt,
    select_native_records,
)
from agent_toolcall_sft.evaluation.runner import (
    DECODING,
    DECODING_VERSION,
    environment_fingerprint,
    load_model,
    run_split,
    stride_sample,
    summarise_generations,
)
from agent_toolcall_sft.evaluation.scoring import (
    native_auxiliary_metrics,
    schema_error_taxonomy,
    score_record,
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


def execute(args) -> Path:
    all_records = read_records(args.split)
    destination = reserve_destination(args.output_dir / args.tag)
    verify_manifest_records(args.manifest, all_records)

    selected = select_native_records(all_records)
    records = stride_sample(selected, args.limit) if args.limit else selected
    print(
        f"selected {len(selected)} gold tool-call records; "
        f"evaluating {len(records)} from {args.split}"
    )

    model, tokenizer = load_model(args.model)
    print(f"loaded {args.model}")
    generations = run_split(
        model, tokenizer, records, prompt_builder=build_native_prompt
    )
    scores = [
        score_record(record, generation.raw_output)
        for record, generation in zip(records, generations, strict=True)
    ]

    summary = {
        "protocol": "native_hermes_auxiliary",
        "prompt_version": NATIVE_HERMES_PROMPT_VERSION,
        "selection_rule": NATIVE_SELECTION_RULE,
        "split": str(args.split),
        "source_records": len(all_records),
        "selected_records": len(selected),
        "evaluated_records": len(records),
        **summarise_generations(generations),
        "auxiliary_metrics": native_auxiliary_metrics(scores),
        "schema_errors": schema_error_taxonomy(scores),
    }
    environment = environment_fingerprint(
        args.model, prompt_version=NATIVE_HERMES_PROMPT_VERSION
    )
    metadata = build_run_metadata(
        manifest_path=args.manifest,
        records=all_records,
        model_source=args.model,
        prompt_version=NATIVE_HERMES_PROMPT_VERSION,
        decoding_version=DECODING_VERSION,
        decoding=asdict(DECODING),
        environment=environment,
    )
    write_frozen_evidence(
        destination,
        predictions=build_prediction_rows(records, generations, scores),
        summary=summary,
        metadata=metadata,
    )
    print(json.dumps(summary["auxiliary_metrics"], ensure_ascii=False, indent=2))
    print(f"\nwrote frozen evidence to {destination}")
    return destination


def main() -> None:
    execute(build_parser().parse_args())


if __name__ == "__main__":
    main()
