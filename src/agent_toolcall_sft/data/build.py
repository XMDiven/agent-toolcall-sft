"""Regenerate the corpus, its splits and the manifest that describes them.

The manifest is the only committed evidence for the dataset -- the splits
themselves stay out of Git. Keeping the four generating calls behind one
command is what lets anyone recompute the fingerprints and the leakage
verdict instead of taking them on trust.

The seed stays pinned to `CORPUS_SEED`: a flag here would only invite
manifests that no longer describe the frozen corpus.
"""

import argparse
from pathlib import Path

from agent_toolcall_sft.data.corpus import (
    CORPUS_SEED,
    build_corpus,
    build_manifest,
    split_corpus,
    write_split,
)


def build(output_dir: Path) -> dict[str, Path]:
    """Generate, split and describe the corpus under `output_dir`."""
    splits = split_corpus(build_corpus(seed_base=CORPUS_SEED), seed=CORPUS_SEED)
    manifest = build_manifest(splits, seed=CORPUS_SEED)

    return write_split(output_dir, splits, manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="parent of the processed/ and manifests/ directories",
    )
    args = parser.parse_args()

    for name, path in sorted(build(args.output_dir).items()):
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
