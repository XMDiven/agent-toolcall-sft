"""Record what a training run was given, before it is given anything.

ROADMAP 2.4 wants the commit, the config, the data manifest, the dependency
versions and the GPU captured up front. Written afterwards, these fields
describe whatever the tree happened to look like when the run ended, which is
exactly the ambiguity the frozen-evaluation guard exists to prevent.

The hashes cover the files themselves, so a manifest edited between two runs
cannot pass as the same input.
"""

import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent_toolcall_sft.evaluation.evidence import (
    _git_commit,
    _git_status_porcelain,
    _package_versions,
    sha256_file,
)

REQUIRED_KEYS = {
    "started_at",
    "git",
    "config",
    "manifest",
    "train_file",
    "eval_file",
    "model",
    "runtime",
    "gpu",
}


def _file_record(path: Path | str) -> dict:
    path = Path(path)
    return {"path": str(path), "sha256": sha256_file(path)}


def _gpu() -> dict:
    try:
        import torch
    except ImportError:
        return {"available": False}

    if not torch.cuda.is_available():
        return {"available": False}

    properties = torch.cuda.get_device_properties(0)

    return {
        "available": True,
        "name": properties.name,
        "total_vram_gib": round(properties.total_memory / 1024**3, 2),
        "torch": torch.__version__,
    }


def capture_provenance(
    config: Path | str,
    manifest: Path | str,
    train_file: Path | str,
    eval_file: Path | str,
    model: str,
) -> dict:
    """Snapshot every input coordinate of a training run."""
    return {
        "started_at": datetime.now(UTC).isoformat(),
        "git": {
            "commit": _git_commit(),
            "worktree_clean": not _git_status_porcelain(),
        },
        "config": _file_record(config),
        "manifest": _file_record(manifest),
        "train_file": _file_record(train_file),
        "eval_file": _file_record(eval_file),
        "model": {"source": str(model)},
        "runtime": {
            "python": platform.python_version(),
            "platform": sys.platform,
            "packages": _package_versions(),
        },
        "gpu": _gpu(),
    }
