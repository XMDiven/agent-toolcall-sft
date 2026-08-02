"""The corpus build entrypoint must be runnable and its manifest must be current."""

import json
from pathlib import Path

from agent_toolcall_sft.data.build import build
from agent_toolcall_sft.data.corpus import (
    CORPUS_SEED,
    build_corpus,
    build_manifest,
    split_corpus,
)

REPO_MANIFEST = Path(__file__).resolve().parents[1] / "data/manifests/split_v2.json"


def test_build_writes_splits_and_a_gated_manifest(tmp_path):
    written = build(tmp_path)

    assert sorted(written) == ["manifest", "test", "train", "valid"]
    assert [len(written[name].read_text().splitlines()) for name in ("train", "valid", "test")] == [
        2000,
        300,
        500,
    ]

    manifest = json.loads(written["manifest"].read_text())
    assert "shared_parameterized_hashes" in manifest["leakage"]
    assert manifest["leakage_clean"] is True


def test_repo_manifest_matches_current_code():
    """The committed manifest must be reproducible from the code that ships with it."""
    splits = split_corpus(build_corpus(), seed=CORPUS_SEED)
    assert json.loads(REPO_MANIFEST.read_text()) == build_manifest(splits, seed=CORPUS_SEED)
