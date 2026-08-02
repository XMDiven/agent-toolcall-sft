"""Assemble the full corpus and split it without leaking templates.

Splitting holds whole `template_key` groups together. The leak this guards
against is the same core sentence appearing on both sides wearing different
wrappers -- "退货政策是什么？" in training and "你好，退货政策是什么？谢谢。"
in the test set would let memorisation pass for generalisation.

Grouping by `scenario_family` instead would be stricter, but it would hand
whole scenario types to the test set and turn the evaluation into a question
about transfer to unseen scenarios rather than about tool routing. See the
note under ROADMAP 1.3.
"""

import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from agent_toolcall_sft.data.families import ALL_FAMILIES, FAMILY_QUOTAS
from agent_toolcall_sft.data.generation import TEMPLATE_VERSION, generate_family
from agent_toolcall_sft.data.records import DatasetRecord, write_records

SPLIT_SIZES: dict[str, int] = {"train": 2000, "valid": 300, "test": 500}

CORPUS_SEED = 20260801

# Character n-gram size and Jaccard threshold for the near-duplicate sweep.
SHINGLE_SIZE = 4
NEAR_DUPLICATE_THRESHOLD = 0.85

_PUNCTUATION = re.compile(r"[\s\W_]+", flags=re.UNICODE)
_SYNTHETIC_ORDER_ID = re.compile(r"ORD-\d{6}")


class SplitError(RuntimeError):
    """The corpus could not be split into the requested exact sizes."""


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def build_corpus(seed_base: int = CORPUS_SEED) -> list[DatasetRecord]:
    """Generate every family at its ROADMAP quota."""
    records: list[DatasetRecord] = []
    for family in ALL_FAMILIES:
        records.extend(
            generate_family(family, FAMILY_QUOTAS[family.name], seed_base=seed_base)
        )

    return records


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def _group_by_template(
    records: list[DatasetRecord],
) -> dict[str, list[DatasetRecord]]:
    groups: dict[str, list[DatasetRecord]] = defaultdict(list)
    for record in records:
        groups[record.template_key].append(record)

    return groups


def _assign_within_family(
    records: list[DatasetRecord], sizes: dict[str, int], total: int, seed: int
) -> dict[str, str]:
    """Hand each template key to the split furthest below its fair share.

    Shares are computed per family so every split keeps the corpus-level mix
    of domains and actions instead of collecting whole families.
    """
    family = records[0].scenario_family
    groups = _group_by_template(records)
    keys = sorted(groups)
    random.Random(f"{seed}:{family}").shuffle(keys)

    share = {name: len(records) * size / total for name, size in sizes.items()}
    filled = dict.fromkeys(sizes, 0)
    assignment: dict[str, str] = {}

    for key in sorted(keys, key=lambda k: -len(groups[k])):
        name = max(sizes, key=lambda n: share[n] - filled[n])
        assignment[key] = name
        filled[name] += len(groups[key])

    return assignment


def _rebalance(
    assignment: dict[str, str],
    groups: dict[str, list[DatasetRecord]],
    sizes: dict[str, int],
) -> None:
    """Move whole groups until every split holds exactly its target count.

    Groups move intact, so no template key is ever split across two files.
    """
    filled = Counter()
    for key, name in assignment.items():
        filled[name] += len(groups[key])

    while True:
        over = [n for n in sizes if filled[n] > sizes[n]]
        under = [n for n in sizes if filled[n] < sizes[n]]
        if not over or not under:
            break

        source = max(over, key=lambda n: filled[n] - sizes[n])
        target = max(under, key=lambda n: sizes[n] - filled[n])
        room = min(filled[source] - sizes[source], sizes[target] - filled[target])

        movable = [
            key
            for key, name in assignment.items()
            if name == source and len(groups[key]) <= room
        ]
        if not movable:
            raise SplitError(
                f"cannot move {room} records from {source} to {target}: "
                "every remaining group is too large"
            )

        key = max(movable, key=lambda k: len(groups[k]))
        assignment[key] = target
        filled[source] -= len(groups[key])
        filled[target] += len(groups[key])


def split_corpus(
    records: list[DatasetRecord],
    sizes: dict[str, int] | None = None,
    seed: int = CORPUS_SEED,
) -> dict[str, list[DatasetRecord]]:
    """Split records into exact-sized splits that share no template key."""
    sizes = sizes or SPLIT_SIZES
    if sum(sizes.values()) != len(records):
        raise SplitError(
            f"split sizes sum to {sum(sizes.values())} but the corpus holds "
            f"{len(records)} records"
        )

    by_family: dict[str, list[DatasetRecord]] = defaultdict(list)
    for record in records:
        by_family[record.scenario_family].append(record)

    assignment: dict[str, str] = {}
    for family_records in (by_family[name] for name in sorted(by_family)):
        assignment.update(
            _assign_within_family(family_records, sizes, len(records), seed)
        )

    groups = _group_by_template(records)
    _rebalance(assignment, groups, sizes)

    splits: dict[str, list[DatasetRecord]] = {name: [] for name in sizes}
    for key, name in assignment.items():
        splits[name].extend(groups[key])

    for name, size in sizes.items():
        splits[name].sort(key=lambda record: record.id)
        if len(splits[name]) != size:
            raise SplitError(f"{name} holds {len(splits[name])} records, want {size}")

    return splits


# ---------------------------------------------------------------------------
# Leakage checks
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Fold width, case and punctuation so cosmetic edits stop hiding a match."""
    return _PUNCTUATION.sub("", unicodedata.normalize("NFKC", text).casefold())


def normalize_synthetic_parameters(text: str) -> str:
    """Replace generated parameter values with their stable sentence skeleton."""
    return _SYNTHETIC_ORDER_ID.sub("ORD-NNNNNN", text)


def _content(record: DatasetRecord) -> str:
    return "\n".join(message.content for message in record.messages)


def _shingles(text: str) -> set[str]:
    folded = normalize(text)
    if len(folded) <= SHINGLE_SIZE:
        return {folded}

    return {
        folded[i : i + SHINGLE_SIZE]
        for i in range(len(folded) - SHINGLE_SIZE + 1)
    }


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_near_duplicates(
    splits: dict[str, list[DatasetRecord]],
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
) -> list[tuple[str, str, float]]:
    """Return cross-split record pairs whose shingle Jaccard clears threshold.

    An inverted index keeps this to the pairs that actually share text rather
    than to every pair in the corpus.
    """
    shingles: dict[str, set[str]] = {}
    split_of: dict[str, str] = {}
    index: dict[str, list[str]] = defaultdict(list)

    for name, records in splits.items():
        for record in records:
            shingles[record.id] = _shingles(_content(record))
            split_of[record.id] = name

    for record_id, grams in shingles.items():
        for gram in grams:
            index[gram].append(record_id)

    matches: list[tuple[str, str, float]] = []
    for record_id, grams in shingles.items():
        shared: Counter[str] = Counter()
        for gram in grams:
            for other in index[gram]:
                if other > record_id and split_of[other] != split_of[record_id]:
                    shared[other] += 1

        for other, overlap in shared.items():
            union = len(grams) + len(shingles[other]) - overlap
            score = overlap / union if union else 0.0
            if score >= threshold:
                matches.append((record_id, other, round(score, 4)))

    return sorted(matches)


def leakage_report(splits: dict[str, list[DatasetRecord]]) -> dict:
    """Summarise every cross-split overlap the roadmap asks us to rule out."""
    keys = {n: {r.template_key for r in rs} for n, rs in splits.items()}
    families = {n: {r.scenario_family for r in rs} for n, rs in splits.items()}
    exact = {n: {_digest(_content(r)) for r in rs} for n, rs in splits.items()}
    folded = {n: {_digest(normalize(_content(r))) for r in rs} for n, rs in splits.items()}
    parameterized = {
        n: {
            _digest(normalize(normalize_synthetic_parameters(_content(record))))
            for record in records
        }
        for n, records in splits.items()
    }

    names = sorted(splits)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1 :]]

    return {
        "shared_template_keys": {
            f"{a}|{b}": sorted(keys[a] & keys[b]) for a, b in pairs
        },
        "shared_content_hashes": {
            f"{a}|{b}": len(exact[a] & exact[b]) for a, b in pairs
        },
        "shared_normalized_hashes": {
            f"{a}|{b}": len(folded[a] & folded[b]) for a, b in pairs
        },
        "shared_parameterized_hashes": {
            f"{a}|{b}": len(parameterized[a] & parameterized[b])
            for a, b in pairs
        },
        "near_duplicate_pairs": find_near_duplicates(splits),
        "shared_scenario_families": {
            f"{a}|{b}": sorted(families[a] & families[b]) for a, b in pairs
        },
    }


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _split_summary(records: list[DatasetRecord]) -> dict:
    # Hash the whole record, not just its text. An earlier version covered only
    # id + template_key + messages, which meant tools, safety_tags and even
    # expected_decision could be edited without moving the digest -- a frozen
    # test set whose answers were not actually frozen.
    payload = "\n".join(
        json.dumps(
            r.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for r in records
    )

    return {
        "count": len(records),
        "sha256": _digest(payload),
        "template_keys": len({r.template_key for r in records}),
        "by_domain": dict(sorted(Counter(r.domain for r in records).items())),
        "by_action": dict(sorted(Counter(r.expected_action for r in records).items())),
        "by_family": dict(
            sorted(Counter(r.scenario_family for r in records).items())
        ),
    }


def build_manifest(splits: dict[str, list[DatasetRecord]], seed: int) -> dict:
    """Describe the split precisely enough to reproduce and audit it."""
    report = leakage_report(splits)

    return {
        "template_version": TEMPLATE_VERSION,
        "corpus_seed": seed,
        "split_seed": seed,
        "split_unit": "template_key",
        "total_records": sum(len(records) for records in splits.values()),
        "splits": {
            name: _split_summary(records) for name, records in sorted(splits.items())
        },
        "leakage": report,
        "leakage_clean": (
            not any(report["shared_template_keys"].values())
            and not any(report["shared_content_hashes"].values())
            and not any(report["shared_normalized_hashes"].values())
            and not any(report["shared_parameterized_hashes"].values())
            and not report["near_duplicate_pairs"]
        ),
    }


def write_split(
    output_dir: Path, splits: dict[str, list[DatasetRecord]], manifest: dict
) -> dict[str, Path]:
    """Write the jsonl splits and the manifest that describes them."""
    processed = output_dir / "processed"
    manifests = output_dir / "manifests"
    processed.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for name, records in splits.items():
        path = processed / f"{name}.jsonl"
        write_records(path, records)
        written[name] = path

    manifest_path = manifests / f"split_{TEMPLATE_VERSION}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written["manifest"] = manifest_path

    return written
