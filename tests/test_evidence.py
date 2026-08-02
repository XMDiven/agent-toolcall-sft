import hashlib
import json
import stat
import subprocess
from types import SimpleNamespace

import pytest
from test_evaluation import make_record

from agent_toolcall_sft.data.corpus import _split_summary
from agent_toolcall_sft.evaluation.evidence import (
    EvidenceExistsError,
    build_run_metadata,
    execute_frozen_run,
    reserve_destination,
    verify_manifest_records,
    write_frozen_evidence,
)
from agent_toolcall_sft.evaluation.runner import Generation


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
    }
    for name, content in model_files.items():
        (model_dir / name).write_bytes(content)
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    records = [make_record()]
    environment = {"gpu": "Fake GPU", "peak_vram_gib": 1.5}

    metadata = build_run_metadata(
        manifest_path=manifest,
        records=records,
        model_source=str(model_dir),
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
    assert metadata["manifest"]["path"] == str(manifest)
    assert metadata["model"]["file_hashes_status"] == "available"
    assert metadata["model"]["source"] == str(model_dir)
    assert list(metadata["model"]["file_hashes"]) == [
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "model.safetensors.index.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
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

    metadata = build_run_metadata(
        manifest_path=manifest,
        records=[make_record()],
        model_source="Qwen/Qwen3-1.7B",
        prompt_version="production_json_v2",
        decoding_version="v1",
        decoding={},
        environment={},
    )

    assert metadata["model"]["source"] == "Qwen/Qwen3-1.7B"
    assert metadata["model"]["file_hashes"] == {}
    assert metadata["model"]["file_hashes_status"] == "unavailable_remote_source"


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
        lambda model: ("model", "tokenizer"),
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
