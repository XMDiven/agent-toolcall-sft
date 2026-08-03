"""A training run must be traceable to the exact inputs that produced it."""

import json

import pytest

from agent_toolcall_sft.training.provenance import REQUIRED_KEYS, capture_provenance


@pytest.fixture
def inputs(tmp_path):
    config = tmp_path / "qlora.yaml"
    config.write_text("lora:\n  r: 16\n", encoding="utf-8")
    manifest = tmp_path / "split.json"
    manifest.write_text(json.dumps({"total_records": 2800}), encoding="utf-8")
    train = tmp_path / "train.jsonl"
    train.write_text('{"id": "a"}\n', encoding="utf-8")
    evaluation = tmp_path / "valid.jsonl"
    evaluation.write_text('{"id": "b"}\n', encoding="utf-8")

    return config, manifest, train, evaluation


def test_every_required_section_is_present(inputs):
    record = capture_provenance(*inputs, model="/models/Qwen3-1.7B")
    assert REQUIRED_KEYS <= set(record)


def test_each_input_file_is_hashed(inputs):
    record = capture_provenance(*inputs, model="/models/Qwen3-1.7B")

    for section in ("config", "manifest", "train_file", "eval_file"):
        assert len(record[section]["sha256"]) == 64
        assert record[section]["path"]


def test_editing_the_config_changes_its_hash(inputs):
    config, manifest, train, evaluation = inputs
    before = capture_provenance(config, manifest, train, evaluation, model="m")
    config.write_text("lora:\n  r: 32\n", encoding="utf-8")
    after = capture_provenance(config, manifest, train, evaluation, model="m")

    assert before["config"]["sha256"] != after["config"]["sha256"]


def test_git_and_runtime_are_recorded(inputs):
    record = capture_provenance(*inputs, model="m")

    assert len(record["git"]["commit"]) == 40
    assert isinstance(record["git"]["worktree_clean"], bool)
    assert record["runtime"]["python"]
    assert "torch" in record["runtime"]["packages"]


def test_the_record_is_json_serialisable(inputs):
    json.dumps(capture_provenance(*inputs, model="m"))
