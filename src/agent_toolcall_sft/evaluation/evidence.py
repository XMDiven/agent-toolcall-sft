"""Reserve, describe, and freeze reproducible baseline evidence."""

import argparse
import ctypes
import errno
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from contextlib import contextmanager
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
_COMMIT_REVISION = re.compile(r"[0-9a-fA-F]{40}")
_MODEL_FILE_SUFFIXES = frozenset(
    {
        ".bin",
        ".jinja",
        ".json",
        ".merges",
        ".model",
        ".py",
        ".safetensors",
        ".tiktoken",
        ".txt",
        ".vocab",
    }
)


class EvidenceExistsError(RuntimeError):
    """A run tag is already reserved and must never be overwritten."""


def positive_int(value: str) -> int:
    """Parse a strictly positive smoke-test limit."""
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


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


def _path_exists(path: Path) -> bool:
    """Treat broken symlinks as occupied evidence paths."""
    return os.path.lexists(path)


def _cleanup_owned_staging(staging: Path, parent: Path, prefix: str) -> None:
    """Remove only a validated staging directory created for this run."""
    if not staging.exists() and not staging.is_symlink():
        return
    if staging.parent.resolve() != parent.resolve() or not staging.name.startswith(
        prefix
    ):
        raise RuntimeError(f"refusing to clean unowned staging path: {staging}")
    if staging.is_symlink():
        raise RuntimeError(f"refusing to follow staging symlink: {staging}")

    staging.chmod(0o700)
    for root, directories, files in os.walk(staging, topdown=False, followlinks=False):
        root_path = Path(root)
        root_path.chmod(0o700)
        for name in files:
            path = root_path / name
            if path.is_symlink():
                path.unlink()
            else:
                path.chmod(0o600)
                path.unlink()
        for name in directories:
            path = root_path / name
            if path.is_symlink():
                path.unlink()
            else:
                path.chmod(0o700)
                path.rmdir()
    staging.rmdir()


def _remove_owned_lock(lock: Path, token: str) -> None:
    try:
        if lock.read_text(encoding="utf-8") == token:
            lock.unlink()
    except FileNotFoundError:
        pass


def _atomic_publish_noreplace(staging: Path, final: Path) -> None:
    """Atomically rename staging while asking the OS to reject any target."""
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(staging)
    destination = os.fsencode(final)
    if sys.platform.startswith("linux"):
        try:
            rename = libc.renameat2
        except AttributeError as error:
            raise RuntimeError(
                "atomic no-replace publish requires renameat2 on Linux"
            ) from error
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, source, -100, destination, 1)
    elif sys.platform == "darwin":
        try:
            rename = libc.renamex_np
        except AttributeError as error:
            raise RuntimeError(
                "atomic no-replace publish requires renamex_np on Darwin"
            ) from error
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(source, destination, 0x00000004)
    else:
        raise RuntimeError(
            f"atomic no-replace publish is unsupported on {sys.platform!r}"
        )

    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise EvidenceExistsError(
            f"{final} already exists; refusing to replace frozen evidence"
        )
    raise OSError(error_number, os.strerror(error_number), str(final))


@contextmanager
def staged_evidence_destination(final: Path):
    """Hold an exclusive sibling lock and atomically publish one frozen run.

    The lock coordinates cooperating writers. The OS-level no-replace rename
    also rejects a final path created by any process during the publish race.
    """
    parent = final.parent
    parent.mkdir(parents=True, exist_ok=True)
    if _path_exists(final):
        raise EvidenceExistsError(
            f"{final} already exists; rerun with a different --tag"
        )

    lock = parent / f".{final.name}.lock"
    token = uuid.uuid4().hex
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token)
    except FileExistsError as error:
        raise EvidenceExistsError(
            f"{lock} already exists; a prior run may have been interrupted; "
            "inspect it before removing it"
        ) from error

    prefix = f".{final.name}.staging-"
    staging: Path | None = None
    try:
        if _path_exists(final):
            raise EvidenceExistsError(
                f"{final} appeared while acquiring the lock; refusing to overwrite it"
            )
        staging = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
        yield staging
        if _path_exists(final):
            raise EvidenceExistsError(
                f"{final} appeared before publish; refusing to overwrite it"
            )
        _atomic_publish_noreplace(staging, final)
        staging = None
    except BaseException:
        if staging is not None:
            _cleanup_owned_staging(staging, parent, prefix)
        raise
    finally:
        _remove_owned_lock(lock, token)


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

    hashes: dict[str, str] = {}
    preferred = [model_path / name for name in _MODEL_METADATA_FILES]
    preferred.extend(sorted(model_path.glob("*.safetensors")))
    remaining = sorted(
        path
        for path in model_path.iterdir()
        if path.is_file()
        and path.suffix.lower() in _MODEL_FILE_SUFFIXES
        and path not in preferred
    )
    for path in [*preferred, *remaining]:
        if path.is_file():
            hashes[path.relative_to(model_path).as_posix()] = sha256_file(path)
    return hashes, "available"


def _model_metadata(model_source: str, model_revision: str | None) -> dict:
    model_hashes, model_hashes_status = _model_file_hashes(model_source)
    is_local = Path(model_source).is_dir()
    return {
        "source": model_source,
        "revision": model_revision,
        "source_type": "local_directory" if is_local else "remote_repository",
        "revision_status": (
            "not_applicable_local_directory" if is_local else "pinned_commit"
        ),
        "file_hashes": model_hashes,
        "file_hashes_status": model_hashes_status,
    }


def adapter_metadata(adapter_source: str | None) -> dict:
    """Pin a LoRA adapter by hashing every file it ships.

    The paired comparison only means something if the adapter behind the
    tuned numbers is identifiable. Recording the path alone would let a
    retrained adapter at the same location pass as the one that was measured.
    """
    if adapter_source is None:
        return {"source": None, "attached": False}

    path = Path(adapter_source)
    if not path.is_dir():
        raise ValueError(f"adapter directory not found: {adapter_source}")

    return {
        "source": adapter_source,
        "attached": True,
        "file_hashes": {
            item.relative_to(path).as_posix(): sha256_file(item)
            for item in sorted(path.rglob("*"))
            if item.is_file()
        },
    }


def validate_model_source(model_source: str, revision: str | None) -> bool:
    """Return whether the source is local, rejecting mutable remote revisions."""
    if Path(model_source).is_dir():
        return True
    if revision is None or _COMMIT_REVISION.fullmatch(revision) is None:
        raise ValueError(
            "remote model --revision must be a 40-character hexadecimal commit SHA"
        )
    return False


def validate_run_preconditions(args) -> None:
    """Reject mutable sources and truncated formal runs before side effects."""
    validate_model_source(args.model, args.revision)
    if args.limit is not None and not args.tag.startswith("smoke-"):
        raise ValueError(
            f"--limit requires a --tag beginning with 'smoke-'; got {args.tag!r}"
        )
    if _git_status_porcelain():
        raise RuntimeError(
            "Git worktree must be clean before a frozen evaluation run"
        )


def _git_status_porcelain() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _select_records(args, selector, all_records):
    selected = selector(all_records)
    records = (
        stride_sample(selected, args.limit)
        if args.limit is not None
        else selected
    )
    return selected, records


def _capture_input_snapshot(args, all_records, selected, records) -> dict:
    verify_manifest_records(args.manifest, all_records)
    status = _git_status_porcelain()
    if status:
        raise RuntimeError(
            "Git worktree must be clean before a frozen evaluation run"
        )
    return {
        "git": {"commit": _git_commit(), "worktree_clean": True},
        "manifest": {
            "path": str(args.manifest),
            "sha256": sha256_file(args.manifest),
        },
        "source_records": _split_summary(all_records),
        "selected_records": _split_summary(selected),
        "evaluated_records": _split_summary(records),
        "model": _model_metadata(args.model, args.revision),
        "adapter": adapter_metadata(getattr(args, "adapter", None)),
    }


def _assert_input_snapshot_unchanged(args, selector, expected: dict) -> None:
    try:
        all_records = read_records(args.split)
        selected, records = _select_records(args, selector, all_records)
        current = _capture_input_snapshot(args, all_records, selected, records)
    except Exception as error:
        raise RuntimeError(
            "evaluation inputs changed during the run; refusing to publish"
        ) from error
    if current != expected:
        raise RuntimeError(
            "evaluation inputs changed during the run; refusing to publish"
        )


def _evaluation_selection(
    *,
    source_records: int,
    selected_records: int,
    records: list[DatasetRecord],
    limit: int | None,
) -> dict:
    record_ids = [record.id for record in records]
    encoded_ids = json.dumps(
        record_ids, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return {
        "source_records": source_records,
        "selected_records": selected_records,
        "evaluated_records": len(records),
        "limit": limit,
        "record_ids": record_ids,
        "record_ids_sha256": hashlib.sha256(encoded_ids).hexdigest(),
    }


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
    prompt_version: str,
    decoding_version: str,
    decoding: dict,
    environment: dict,
    input_snapshot: dict,
    evaluation_selection: dict | None = None,
) -> dict:
    """Combine a pre-load input snapshot with post-run runtime metadata."""
    metadata = {
        "git_commit": input_snapshot["git"]["commit"],
        "worktree_clean": input_snapshot["git"]["worktree_clean"],
        "manifest": input_snapshot["manifest"],
        "test_records": input_snapshot["source_records"],
        "model": input_snapshot["model"],
        "input_snapshot": input_snapshot,
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
    if evaluation_selection is not None:
        metadata["evaluation_selection"] = evaluation_selection
    return metadata


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
        serialized_score = asdict(score)
        serialized_score["called_tool"] = score.called_tool
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
                "score": serialized_score,
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
    model_loader: Callable | None = None,
) -> Path:
    """Execute the shared, fail-closed lifecycle for one frozen protocol."""
    validate_run_preconditions(args)
    all_records = read_records(args.split)
    verify_manifest_records(args.manifest, all_records)
    final = args.output_dir / args.tag
    with staged_evidence_destination(final) as staging:
        selected, records = _select_records(args, selector, all_records)
        if not records:
            raise ValueError("evaluation selection selected no records")
        input_snapshot = _capture_input_snapshot(
            args, all_records, selected, records
        )
        print(
            f"selected {len(selected)} records; evaluating {len(records)} "
            f"from {args.split}"
        )

        model, tokenizer = (
            model_loader(args)
            if model_loader is not None
            else load_model(args.model, revision=args.revision)
        )
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
            input_snapshot=input_snapshot,
            prompt_version=prompt_version,
            decoding_version=DECODING_VERSION,
            decoding=asdict(DECODING),
            environment=environment_fingerprint(
                args.model, prompt_version=prompt_version
            ),
            evaluation_selection=_evaluation_selection(
                source_records=len(all_records),
                selected_records=len(selected),
                records=records,
                limit=args.limit,
            ),
        )
        write_frozen_evidence(
            staging,
            predictions=build_prediction_rows(records, generations, scores),
            summary=summary,
            metadata=metadata,
        )
        _assert_input_snapshot_unchanged(args, selector, input_snapshot)
    print(f"wrote frozen evidence to {final}")
    return final
