import hashlib
import json
import stat

import pytest
from test_evaluation import make_record

from agent_toolcall_sft.data.corpus import _split_summary
from agent_toolcall_sft.evaluation.evidence import (
    EvidenceExistsError,
    build_run_metadata,
    reserve_destination,
    verify_manifest_records,
    write_frozen_evidence,
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


def test_metadata_hashes_existing_local_model_files(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("config", encoding="utf-8")
    (model_dir / "model-00002-of-00002.safetensors").write_bytes(b"two")
    (model_dir / "model-00001-of-00002.safetensors").write_bytes(b"one")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    metadata = build_run_metadata(
        manifest_path=manifest,
        records=[make_record()],
        model_source=str(model_dir),
        prompt_version="production_json_v2",
        decoding_version="v1",
        decoding={"do_sample": False},
        environment={"gpu": None, "peak_vram_gib": 0.0},
    )

    assert metadata["model"]["file_hashes_status"] == "available"
    assert list(metadata["model"]["file_hashes"]) == [
        "config.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
    ]
    assert metadata["manifest"]["sha256"] == hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    assert metadata["test_records"]["sha256"] == _split_summary(
        [make_record()]
    )["sha256"]


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
