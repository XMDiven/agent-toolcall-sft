"""Small-sample overfit probe: can this pipeline learn anything at all?

ROADMAP 2.3 asks for 64 balanced examples covering the four decisions and
both domains. Only five of those eight cells exist -- the knowledge domain is
entirely tool calls by design -- so the sample balances across the strata that
are actually present rather than inventing empty ones.

If behaviour accuracy on these very examples does not rise sharply, the fault
is in the template, the label mask, the tokenizer or the adapter injection.
Reaching for the learning rate at that point only hides the real defect.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from agent_toolcall_sft.data.records import DatasetRecord


def stratum_of(record: DatasetRecord) -> str:
    """Group by the pair the probe needs to cover."""
    return f"{record.domain}:{record.expected_action}"


def select_balanced(records: list[DatasetRecord], size: int) -> list[DatasetRecord]:
    """Take `size` records spread as evenly as possible over present strata."""
    pools: dict[str, list[DatasetRecord]] = defaultdict(list)
    for record in records:
        pools[stratum_of(record)].append(record)

    names = sorted(pools)
    if size < len(names):
        raise ValueError(f"size must be at least {len(names)} to cover every stratum")

    base, extra = divmod(size, len(names))
    selected: list[DatasetRecord] = []
    for index, name in enumerate(names):
        quota = base + (1 if index < extra else 0)
        pool = pools[name]
        if len(pool) < quota:
            raise ValueError(f"{name} holds {len(pool)} records, needs {quota}")
        selected.extend(sorted(pool, key=lambda r: r.id)[:quota])

    return selected


def write_slice(records: list[DatasetRecord], path: Path) -> Path:
    """Persist the probe slice so training and scoring read the same rows."""
    from agent_toolcall_sft.data.records import write_records

    path.parent.mkdir(parents=True, exist_ok=True)
    write_records(path, records)

    return path


def main() -> None:
    from agent_toolcall_sft.data.corpus import build_corpus, split_corpus

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size", type=int, default=64)
    parser.add_argument("--out", type=Path, default=Path("artifacts/overfit/slice.jsonl"))
    args = parser.parse_args()

    sample = select_balanced(split_corpus(build_corpus())["train"], args.size)
    write_slice(sample, args.out)

    counts: dict[str, int] = defaultdict(int)
    for record in sample:
        counts[stratum_of(record)] += 1
    print(json.dumps({"path": str(args.out), "strata": dict(counts)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
