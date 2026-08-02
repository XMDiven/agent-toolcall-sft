"""Reserve, describe, and freeze reproducible baseline evidence."""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from agent_toolcall_sft.data.corpus import _split_summary
from agent_toolcall_sft.data.records import DatasetRecord, read_records
from agent_toolcall_sft.evaluation.runner import (
    DECODING,
    DECODING_VERSION,
    Generation,
    environment_fingerprint,
    load_model,
    run_split,
    stride_sample,
    summarise_generations,
)
from agent_toolcall_sft.evaluation.scoring import RecordScore, score_record

_MODEL_METADATA_FILES = (
    "config.json",
    "generation_config.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "model.safetensors.index.json",
)
_CORE_PACKAGES = ("torch", "transformers", "pydantic", "jsonschema")


class EvidenceExistsError(RuntimeError):
    """A run tag is already reserved and must never be overwritten."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reserve_destination(path: Path) -> Path:
    """Atomically reserve a never-before-used run directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError as error:
        raise EvidenceExistsError(
            f"{path} already exists; rerun with a different --tag"
        ) from error
    return path


def verify_manifest_records(
    manifest_path: Path,
    records: list[DatasetRecord],
    split_name: str = "test",
) -> dict:
    """Fail closed when loaded records differ from the frozen manifest."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        frozen = manifest["splits"][split_name]
        expected_hash = frozen["sha256"]
    except (KeyError, TypeError) as error:
        raise ValueError(
            f"{manifest_path} has no canonical hash for split {split_name!r}"
        ) from error

    current = _split_summary(records)
    if current["sha256"] != expected_hash:
        raise ValueError(
            f"current {split_name} record set does not match manifest {manifest_path}: "
            f"expected {expected_hash}, got {current['sha256']}"
        )
    if "count" in frozen and current["count"] != frozen["count"]:
        raise ValueError(
            f"current {split_name} count does not match manifest {manifest_path}: "
            f"expected {frozen['count']}, got {current['count']}"
        )
    return current


def _model_file_hashes(model_source: str) -> tuple[dict[str, str], str]:
    model_path = Path(model_source)
    if not model_path.is_dir():
        return {}, "unavailable_remote_source"

    candidates = [model_path / name for name in _MODEL_METADATA_FILES]
    candidates.extend(sorted(model_path.glob("*.safetensors")))
    hashes: dict[str, str] = {}
    for path in candidates:
        if path.is_file() and path.name not in hashes:
            hashes[path.name] = sha256_file(path)
    return hashes, "available"


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package in _CORE_PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unavailable"
    return versions


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_run_metadata(
    *,
    manifest_path: Path,
    records: list[DatasetRecord],
    model_source: str,
    prompt_version: str,
    decoding_version: str,
    decoding: dict,
    environment: dict,
) -> dict:
    """Capture immutable inputs and the execution environment for one run."""
    model_hashes, model_hashes_status = _model_file_hashes(model_source)
    return {
        "git_commit": _git_commit(),
        "manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
        },
        "test_records": _split_summary(records),
        "model": {
            "source": model_source,
            "file_hashes": model_hashes,
            "file_hashes_status": model_hashes_status,
        },
        "protocol": {
            "prompt_version": prompt_version,
            "decoding_version": decoding_version,
            "decoding": decoding,
        },
        "runtime": {
            "python": platform.python_version(),
            "packages": _package_versions(),
        },
        "environment": environment,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_frozen_evidence(
    destination: Path,
    *,
    predictions: list[dict],
    summary: dict,
    metadata: dict,
) -> None:
    """Write all evidence, hash outputs, then make files and directory read-only."""
    if not destination.is_dir():
        raise ValueError(f"destination was not reserved: {destination}")
    if any(destination.iterdir()):
        raise EvidenceExistsError(f"reserved destination is not empty: {destination}")

    predictions_path = destination / "predictions.jsonl"
    with predictions_path.open("x", encoding="utf-8") as handle:
        for prediction in predictions:
            handle.write(json.dumps(prediction, ensure_ascii=False, sort_keys=True) + "\n")

    summary_path = destination / "summary.json"
    _write_json(summary_path, summary)

    frozen_metadata = dict(metadata)
    frozen_metadata["artifacts"] = {
        "predictions.jsonl": {"sha256": sha256_file(predictions_path)},
        "summary.json": {"sha256": sha256_file(summary_path)},
    }
    metadata_path = destination / "metadata.json"
    _write_json(metadata_path, frozen_metadata)

    for path in (predictions_path, summary_path, metadata_path):
        os.chmod(path, 0o444)
    os.chmod(destination, 0o555)


def build_prediction_rows(
    records: list[DatasetRecord],
    generations: list[Generation],
    scores: list[RecordScore],
) -> list[dict]:
    """Serialize the shared per-record evidence shape for either protocol."""
    rows: list[dict] = []
    for record, generation, score in zip(
        records, generations, scores, strict=True
    ):
        rows.append(
            {
                "record_id": record.id,
                "scenario_family": record.scenario_family,
                "domain": record.domain,
                "tools": record.tools,
                "user": record.messages[-1].content,
                "expected": record.expected_decision.model_dump(mode="json"),
                "raw_output": generation.raw_output,
                "latency_ms": generation.latency_ms,
                "prompt_tokens": generation.prompt_tokens,
                "completion_tokens": generation.completion_tokens,
                "score": asdict(score),
            }
        )
    return rows


def execute_frozen_run(
    args,
    *,
    selector: Callable[[list[DatasetRecord]], list[DatasetRecord]],
    prompt_builder: Callable,
    prompt_version: str,
    summary_builder: Callable[..., dict],
) -> Path:
    """Execute the shared, fail-closed lifecycle for one frozen protocol."""
    all_records = read_records(args.split)
    verify_manifest_records(args.manifest, all_records)
    destination = reserve_destination(args.output_dir / args.tag)

    selected = selector(all_records)
    records = stride_sample(selected, args.limit) if args.limit else selected
    print(
        f"selected {len(selected)} records; evaluating {len(records)} "
        f"from {args.split}"
    )

    model, tokenizer = load_model(args.model)
    print(f"loaded {args.model}")
    generations = run_split(
        model, tokenizer, records, prompt_builder=prompt_builder
    )
    scores = [
        score_record(record, generation.raw_output)
        for record, generation in zip(records, generations, strict=True)
    ]
    performance = summarise_generations(generations)
    summary = summary_builder(
        split=str(args.split),
        source_records=len(all_records),
        selected_records=len(selected),
        evaluated_records=len(records),
        scores=scores,
        performance=performance,
    )
    metadata = build_run_metadata(
        manifest_path=args.manifest,
        records=all_records,
        model_source=args.model,
        prompt_version=prompt_version,
        decoding_version=DECODING_VERSION,
        decoding=asdict(DECODING),
        environment=environment_fingerprint(
            args.model, prompt_version=prompt_version
        ),
    )
    write_frozen_evidence(
        destination,
        predictions=build_prediction_rows(records, generations, scores),
        summary=summary,
        metadata=metadata,
    )
    print(f"wrote frozen evidence to {destination}")
    return destination
