import hashlib
import json
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_evaluation import make_record

from agent_toolcall_sft.data.corpus import _split_summary
from agent_toolcall_sft.evaluation import evidence
from agent_toolcall_sft.evaluation.evidence import (
    EvidenceExistsError,
    build_prediction_rows,
    build_run_metadata,
    execute_frozen_run,
    reserve_destination,
    staged_evidence_destination,
    verify_manifest_records,
    write_frozen_evidence,
)
from agent_toolcall_sft.evaluation.runner import Generation
from agent_toolcall_sft.evaluation.scoring import score_record


@pytest.fixture(autouse=True)
def _clean_worktree(monkeypatch):
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence._git_status_porcelain",
        lambda: "",
    )


def test_reserve_destination_rejects_an_existing_empty_directory(tmp_path):
    destination = tmp_path / "same-tag"
    destination.mkdir()

    with pytest.raises(EvidenceExistsError, match="different --tag"):
        reserve_destination(destination)


def test_reserve_destination_creates_a_new_directory(tmp_path):
    destination = tmp_path / "new-tag"
    reserve_destination(destination)
    assert destination.is_dir()


def test_manifest_hash_mismatch_fails_closed(tmp_path):
    records = [make_record()]
    manifest = {"splits": {"test": {"sha256": "0" * 64}}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match manifest"):
        verify_manifest_records(path, records)


def test_manifest_hash_match_returns_canonical_summary(tmp_path):
    records = [make_record()]
    expected = _split_summary(records)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"splits": {"test": expected}}), encoding="utf-8"
    )

    assert verify_manifest_records(path, records) == expected


def test_write_evidence_hashes_outputs_and_freezes_directory(tmp_path):
    destination = tmp_path / "run"
    reserve_destination(destination)

    write_frozen_evidence(
        destination,
        predictions=[{"record_id": "one", "raw_output": "{}"}],
        summary={"protocol": "production_json"},
        metadata={"git_commit": "abc"},
    )

    metadata = json.loads((destination / "metadata.json").read_text())
    for name in ("predictions.jsonl", "summary.json"):
        digest = hashlib.sha256((destination / name).read_bytes()).hexdigest()
        assert metadata["artifacts"][name]["sha256"] == digest
        assert stat.S_IMODE((destination / name).stat().st_mode) == 0o444
    assert "metadata.json" not in metadata["artifacts"]
    assert stat.S_IMODE((destination / "metadata.json").stat().st_mode) == 0o444
    assert stat.S_IMODE(destination.stat().st_mode) == 0o555


def test_prediction_rows_include_single_and_multi_call_compatibility_fields():
    record = make_record()
    single_raw = json.dumps(
        {
            "action": "tool_call",
            "tool_call": {
                "name": "get_order_status",
                "arguments": {"order_id": "ORD-603256"},
            },
        }
    )
    multi_raw = "\n".join(
        [single_raw, json.dumps({"name": "invented_tool", "arguments": {}})]
    )
    generations = [
        Generation(record.id, single_raw, 1.0, 10, 2),
        Generation(record.id, multi_raw, 1.0, 10, 2),
    ]
    rows = build_prediction_rows(
        [record, record],
        generations,
        [score_record(record, raw) for raw in (single_raw, multi_raw)],
    )

    assert rows[0]["score"]["called_tools"] == ("get_order_status",)
    assert rows[0]["score"]["called_tool"] == "get_order_status"
    assert rows[1]["score"]["called_tools"] == (
        "get_order_status",
        "invented_tool",
    )
    assert rows[1]["score"]["called_tool"] is None


def test_metadata_hashes_existing_local_model_files(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    model_files = {
        "config.json": b"config",
        "generation_config.json": b"generation",
        "tokenizer_config.json": b"tokenizer-config",
        "tokenizer.json": b"tokenizer",
        "model.safetensors.index.json": b"index",
        "model-00002-of-00002.safetensors": b"two",
        "model-00001-of-00002.safetensors": b"one",
        "pytorch_model.bin": b"bin",
        "tokenizer.model": b"model",
        "chat_template.jinja": b"jinja",
        "merges.txt": b"txt",
    }
    for name, content in model_files.items():
        (model_dir / name).write_bytes(content)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    records = [make_record()]
    environment = {"gpu": "Fake GPU", "peak_vram_gib": 1.5}

    snapshot = {
        "git": {"commit": evidence._git_commit(), "worktree_clean": True},
        "manifest": {
            "path": str(manifest),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
        "source_records": _split_summary(records),
        "selected_records": _split_summary(records),
        "evaluated_records": _split_summary(records),
        "model": evidence._model_metadata(str(model_dir), None),
    }
    metadata = build_run_metadata(
        input_snapshot=snapshot,
        prompt_version="production_json_v2",
        decoding_version="v1",
        decoding={"do_sample": False},
        environment=environment,
    )

    assert metadata["git_commit"] == subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert metadata["worktree_clean"] is True
    assert metadata["manifest"]["path"] == str(manifest)
    assert metadata["model"]["file_hashes_status"] == "available"
    assert metadata["model"]["source"] == str(model_dir)
    assert metadata["model"]["revision"] is None
    assert metadata["model"]["revision_status"] == "not_applicable_local_directory"
    assert list(metadata["model"]["file_hashes"]) == [
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "model.safetensors.index.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
        "chat_template.jinja",
        "merges.txt",
        "pytorch_model.bin",
        "tokenizer.model",
    ]
    assert metadata["model"]["file_hashes"] == {
        name: hashlib.sha256(model_files[name]).hexdigest()
        for name in metadata["model"]["file_hashes"]
    }
    assert metadata["manifest"]["sha256"] == hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    assert metadata["test_records"] == _split_summary(records)
    assert metadata["protocol"] == {
        "prompt_version": "production_json_v2",
        "decoding_version": "v1",
        "decoding": {"do_sample": False},
    }
    assert metadata["runtime"]["python"]
    assert set(metadata["runtime"]["packages"]) == {
        "torch",
        "transformers",
        "pydantic",
        "jsonschema",
    }
    assert all(metadata["runtime"]["packages"].values())
    assert metadata["environment"] == environment


def test_remote_model_identifier_marks_file_hashes_unavailable(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    records = [make_record()]
    snapshot = {
        "git": {"commit": evidence._git_commit(), "worktree_clean": True},
        "manifest": {
            "path": str(manifest),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
        "source_records": _split_summary(records),
        "selected_records": _split_summary(records),
        "evaluated_records": _split_summary(records),
        "model": evidence._model_metadata("Qwen/Qwen3-1.7B", "a" * 40),
    }
    metadata = build_run_metadata(
        input_snapshot=snapshot,
        prompt_version="production_json_v2",
        decoding_version="v1",
        decoding={},
        environment={},
    )

    assert metadata["model"]["source"] == "Qwen/Qwen3-1.7B"
    assert metadata["model"]["revision"] == "a" * 40
    assert metadata["model"]["revision_status"] == "pinned_commit"
    assert metadata["model"]["file_hashes"] == {}
    assert metadata["model"]["file_hashes_status"] == "unavailable_remote_source"


def test_metadata_uses_precomputed_input_snapshot_without_live_reads(monkeypatch):
    snapshot = {
        "git": {"commit": "pre-run-commit", "worktree_clean": True},
        "manifest": {"path": "manifest.json", "sha256": "1" * 64},
        "source_records": {"count": 2, "sha256": "2" * 64},
        "selected_records": {"count": 1, "sha256": "3" * 64},
        "evaluated_records": {"count": 1, "sha256": "3" * 64},
        "model": {
            "source": "remote/model",
            "revision": "a" * 40,
            "source_type": "remote_repository",
            "revision_status": "pinned_commit",
            "file_hashes": {},
            "file_hashes_status": "unavailable_remote_source",
        },
    }
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence._git_commit",
        lambda: pytest.fail("metadata must not recapture git"),
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.sha256_file",
        lambda _path: pytest.fail("metadata must not recapture files"),
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence._model_file_hashes",
        lambda _model: pytest.fail("metadata must not recapture model"),
    )

    metadata = build_run_metadata(
        input_snapshot=snapshot,
        prompt_version="test_v1",
        decoding_version="v1",
        decoding={},
        environment={},
        evaluation_selection={"record_ids": ["record_1"]},
    )

    assert metadata["input_snapshot"] == snapshot
    assert metadata["git_commit"] == "pre-run-commit"
    assert metadata["manifest"] == snapshot["manifest"]
    assert metadata["test_records"] == snapshot["source_records"]
    assert metadata["model"] == snapshot["model"]


def test_shared_orchestrator_injects_selection_prompt_and_summary(
    tmp_path, monkeypatch
):
    records = [make_record(id="skip"), make_record(id="keep")]
    split = tmp_path / "test.jsonl"
    split.write_text(
        "".join(record.model_dump_json() + "\n" for record in records),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"splits": {"test": _split_summary(records)}}),
        encoding="utf-8",
    )
    seen = {}
    prompt_builder = object()

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda model, revision=None: ("model", "tokenizer"),
    )

    def fake_run(model, tokenizer, selected, *, prompt_builder):
        seen["ids"] = [record.id for record in selected]
        seen["prompt_builder"] = prompt_builder
        return [Generation("keep", "{}", 1.0, 10, 2)]

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.run_split", fake_run
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.environment_fingerprint",
        lambda model, prompt_version: {"gpu": "fake", "peak_vram_gib": 1.0},
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.score_record",
        lambda record, raw: SimpleNamespace(record_id=record.id),
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.build_prediction_rows",
        lambda records, generations, scores: [{"record_id": records[0].id}],
    )

    def summary_builder(**context):
        seen["summary_context"] = context
        return {"protocol": "injected", **context["performance"]}

    args = SimpleNamespace(
        model="remote/model",
        revision="a" * 40,
        split=split,
        manifest=manifest,
        limit=None,
        tag="shared",
        output_dir=tmp_path / "artifacts",
    )
    destination = execute_frozen_run(
        args,
        selector=lambda source: source[1:],
        prompt_builder=prompt_builder,
        prompt_version="injected_v1",
        summary_builder=summary_builder,
    )

    assert seen["ids"] == ["keep"]
    assert seen["prompt_builder"] is prompt_builder
    assert seen["summary_context"]["source_records"] == 2
    assert seen["summary_context"]["selected_records"] == 1
    assert seen["summary_context"]["evaluated_records"] == 1
    assert json.loads((destination / "summary.json").read_text())["protocol"] == "injected"
    assert list(args.output_dir.iterdir()) == [destination]


def _execution_args(tmp_path, *, tag="lifecycle"):
    model_dir = tmp_path / f"{tag}-model"
    model_dir.mkdir()
    records = [make_record()]
    split = tmp_path / f"{tag}-test.jsonl"
    split.write_text(records[0].model_dump_json() + "\n", encoding="utf-8")
    manifest = tmp_path / f"{tag}-manifest.json"
    manifest.write_text(
        json.dumps({"splits": {"test": _split_summary(records)}}),
        encoding="utf-8",
    )
    return SimpleNamespace(
        model=str(model_dir),
        revision=None,
        split=split,
        manifest=manifest,
        limit=None,
        tag=tag,
        output_dir=tmp_path / "artifacts",
    )


def _assert_no_run_paths(args):
    final = args.output_dir / args.tag
    assert not final.exists()
    if args.output_dir.exists():
        assert not list(args.output_dir.glob(f".{args.tag}.staging-*"))
        assert not (args.output_dir / f".{args.tag}.lock").exists()


def _stub_successful_evaluation(monkeypatch, during_generation=None):
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda *_args, **_kwargs: ("model", "tokenizer"),
    )

    def fake_run(*_args, **_kwargs):
        if during_generation is not None:
            during_generation()
        return [Generation("record_1", "{}", 1.0, 1, 1)]

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.run_split", fake_run
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.score_record",
        lambda record, _raw: SimpleNamespace(record_id=record.id),
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.environment_fingerprint",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.build_prediction_rows",
        lambda *_args: [],
    )


@pytest.mark.parametrize("changed_input", ["manifest", "model", "git_status"])
def test_execute_refuses_publish_when_an_input_changes_during_run(
    tmp_path, monkeypatch, changed_input
):
    args = _execution_args(tmp_path, tag=f"changed-{changed_input}")
    model_config = Path(args.model) / "config.json"
    model_config.write_text("before", encoding="utf-8")

    if changed_input == "manifest":
        def mutate_input():
            payload = json.loads(args.manifest.read_text(encoding="utf-8"))
            payload["diagnostic"] = "changed"
            args.manifest.write_text(json.dumps(payload), encoding="utf-8")
    elif changed_input == "model":
        def mutate_input():
            model_config.write_text("after", encoding="utf-8")
    else:
        statuses = iter(["", "", " M tracked.py\n"])
        monkeypatch.setattr(
            "agent_toolcall_sft.evaluation.evidence._git_status_porcelain",
            lambda: next(statuses),
        )

        def mutate_input():
            return None

    _stub_successful_evaluation(monkeypatch, mutate_input)

    with pytest.raises(RuntimeError, match="inputs changed"):
        execute_frozen_run(
            args,
            selector=lambda source: source,
            prompt_builder=object(),
            prompt_version="test_v1",
            summary_builder=lambda **_context: {"protocol": "test"},
        )

    _assert_no_run_paths(args)


def test_empty_selection_fails_before_model_load_and_publishes_nothing(
    tmp_path, monkeypatch
):
    args = _execution_args(tmp_path, tag="empty-selection")
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda *_args, **_kwargs: pytest.fail("empty selection must not load model"),
    )

    with pytest.raises(ValueError, match="selected no records"):
        execute_frozen_run(
            args,
            selector=lambda _source: [],
            prompt_builder=object(),
            prompt_version="test_v1",
            summary_builder=lambda **_context: {},
        )

    _assert_no_run_paths(args)


@pytest.mark.parametrize(
    "failure_stage",
    ["load", "generation", "summary", "metadata", "write_summary", "readonly"],
)
def test_execute_failure_cleans_owned_staging_lock_and_never_publishes_final(
    tmp_path, monkeypatch, failure_stage
):
    args = _execution_args(tmp_path, tag=f"fail-{failure_stage}")

    if failure_stage == "load":
        monkeypatch.setattr(
            "agent_toolcall_sft.evaluation.evidence.load_model",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("load")),
        )
    else:
        monkeypatch.setattr(
            "agent_toolcall_sft.evaluation.evidence.load_model",
            lambda *_args, **_kwargs: ("model", "tokenizer"),
        )

    if failure_stage == "generation":
        monkeypatch.setattr(
            "agent_toolcall_sft.evaluation.evidence.run_split",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("generation")
            ),
        )
    else:
        monkeypatch.setattr(
            "agent_toolcall_sft.evaluation.evidence.run_split",
            lambda *_args, **_kwargs: [Generation("record_1", "{}", 1.0, 1, 1)],
        )

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.score_record",
        lambda record, _raw: SimpleNamespace(record_id=record.id),
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.environment_fingerprint",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.build_prediction_rows",
        lambda *_args: [],
    )
    if failure_stage == "metadata":
        monkeypatch.setattr(
            "agent_toolcall_sft.evaluation.evidence.build_run_metadata",
            lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("metadata")),
        )
    if failure_stage == "write_summary":
        original_write_json = evidence._write_json

        def fail_summary_write(path, payload):
            if path.name == "summary.json":
                raise RuntimeError("write_summary")
            original_write_json(path, payload)

        monkeypatch.setattr(evidence, "_write_json", fail_summary_write)
    if failure_stage == "readonly":
        def fail_after_freeze(destination, **_kwargs):
            artifact = destination / "partial.json"
            artifact.write_text("partial", encoding="utf-8")
            artifact.chmod(0o444)
            destination.chmod(0o555)
            raise RuntimeError("readonly")

        monkeypatch.setattr(
            "agent_toolcall_sft.evaluation.evidence.write_frozen_evidence",
            fail_after_freeze,
        )

    def summary_builder(**_context):
        if failure_stage == "summary":
            raise RuntimeError("summary")
        return {"protocol": "test"}

    with pytest.raises(RuntimeError, match=failure_stage):
        execute_frozen_run(
            args,
            selector=lambda source: source,
            prompt_builder=object(),
            prompt_version="test_v1",
            summary_builder=summary_builder,
        )

    _assert_no_run_paths(args)


def test_execute_rejects_existing_lock_and_preserves_it(tmp_path, monkeypatch):
    args = _execution_args(tmp_path, tag="locked")
    args.output_dir.mkdir()
    lock = args.output_dir / ".locked.lock"
    lock.write_text("stale diagnostic", encoding="utf-8")
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda *_args, **_kwargs: pytest.fail("locked run must not load model"),
    )

    with pytest.raises(EvidenceExistsError, match="interrupted"):
        execute_frozen_run(
            args,
            selector=lambda source: source,
            prompt_builder=object(),
            prompt_version="test_v1",
            summary_builder=lambda **_context: {},
        )

    assert lock.read_text(encoding="utf-8") == "stale diagnostic"
    assert not (args.output_dir / args.tag).exists()


@pytest.mark.parametrize("occupied_kind", ["empty_directory", "symlink"])
def test_atomic_publish_never_replaces_an_existing_path(
    tmp_path, monkeypatch, occupied_kind
):
    final = tmp_path / "run"
    target = tmp_path / "symlink-target"
    if occupied_kind == "empty_directory":
        final.mkdir()
    else:
        target.mkdir()
        final.symlink_to(target, target_is_directory=True)

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence._path_exists",
        lambda _path: False,
    )

    with (
        pytest.raises(EvidenceExistsError, match="already exists"),
        staged_evidence_destination(final) as staging,
    ):
        (staging / "complete.txt").write_text("complete", encoding="utf-8")

    if occupied_kind == "empty_directory":
        assert final.is_dir()
        assert not (final / "complete.txt").exists()
    else:
        assert final.is_symlink()
        assert not (target / "complete.txt").exists()


def test_atomic_publish_rejects_a_path_created_in_the_publish_race(
    tmp_path, monkeypatch
):
    final = tmp_path / "run"
    checks = 0

    def create_racing_destination(_path):
        nonlocal checks
        checks += 1
        if checks == 3:
            final.mkdir()
        return False

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence._path_exists",
        create_racing_destination,
    )

    with (
        pytest.raises(EvidenceExistsError, match="already exists"),
        staged_evidence_destination(final) as staging,
    ):
        (staging / "complete.txt").write_text("complete", encoding="utf-8")

    assert final.is_dir()
    assert not (final / "complete.txt").exists()


def test_staging_lock_is_private_while_held(tmp_path):
    final = tmp_path / "run"
    lock = tmp_path / ".run.lock"

    with (
        pytest.raises(RuntimeError, match="stop before publish"),
        staged_evidence_destination(final),
    ):
        assert stat.S_IMODE(lock.stat().st_mode) == 0o600
        raise RuntimeError("stop before publish")

    assert not lock.exists()


@pytest.mark.parametrize("revision", [None, "main", "v1.0", "a" * 39])
def test_remote_model_requires_commit_revision_before_load_or_directory(
    tmp_path, monkeypatch, revision
):
    records = [make_record()]
    split = tmp_path / "test.jsonl"
    split.write_text(records[0].model_dump_json() + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"splits": {"test": _split_summary(records)}}),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        model="remote/model",
        revision=revision,
        split=split,
        manifest=manifest,
        limit=None,
        tag="must-not-exist",
        output_dir=tmp_path / "artifacts",
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda *_args, **_kwargs: pytest.fail("invalid revision must not load model"),
    )

    with pytest.raises(ValueError, match="40-character hexadecimal commit SHA"):
        execute_frozen_run(
            args,
            selector=lambda source: source,
            prompt_builder=object(),
            prompt_version="test_v1",
            summary_builder=lambda **_context: {},
        )

    assert not (args.output_dir / args.tag).exists()


def test_local_model_directory_allows_no_revision(tmp_path, monkeypatch):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    records = [make_record()]
    split = tmp_path / "test.jsonl"
    split.write_text(records[0].model_dump_json() + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"splits": {"test": _split_summary(records)}}),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        model=str(model_dir),
        revision=None,
        split=split,
        manifest=manifest,
        limit=None,
        tag="local",
        output_dir=tmp_path / "artifacts",
    )
    seen = {}

    def fake_load(model, revision=None):
        seen["load"] = (model, revision)
        return "model", "tokenizer"

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model", fake_load
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.run_split",
        lambda *_args, **_kwargs: [Generation("record_1", "{}", 1.0, 1, 1)],
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.score_record",
        lambda record, _raw: SimpleNamespace(record_id=record.id),
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.environment_fingerprint",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.build_prediction_rows",
        lambda *_args: [],
    )

    destination = execute_frozen_run(
        args,
        selector=lambda source: source,
        prompt_builder=object(),
        prompt_version="test_v1",
        summary_builder=lambda **_context: {},
    )

    assert seen["load"] == (str(model_dir), None)
    assert destination.is_dir()
