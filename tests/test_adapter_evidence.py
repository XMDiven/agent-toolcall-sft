"""An adapter run must pin the adapter as tightly as the base weights."""

import pytest

from agent_toolcall_sft.evaluation.evidence import adapter_metadata


def _write_adapter(directory, weights: bytes):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "adapter_config.json").write_text('{"r": 16}', encoding="utf-8")
    (directory / "adapter_model.safetensors").write_bytes(weights)
    return directory


def test_absent_adapter_is_reported_not_guessed():
    assert adapter_metadata(None) == {"source": None, "attached": False}


def test_every_adapter_file_is_hashed(tmp_path):
    record = adapter_metadata(str(_write_adapter(tmp_path / "a", b"weights")))

    assert record["attached"] is True
    assert set(record["file_hashes"]) == {
        "adapter_config.json",
        "adapter_model.safetensors",
    }
    assert all(len(h) == 64 for h in record["file_hashes"].values())


def test_swapped_weights_change_the_record(tmp_path):
    directory = _write_adapter(tmp_path / "a", b"weights")
    before = adapter_metadata(str(directory))
    (directory / "adapter_model.safetensors").write_bytes(b"different")
    after = adapter_metadata(str(directory))

    assert before["file_hashes"] != after["file_hashes"]


def test_a_missing_directory_is_refused(tmp_path):
    with pytest.raises(ValueError, match="adapter directory"):
        adapter_metadata(str(tmp_path / "nope"))
