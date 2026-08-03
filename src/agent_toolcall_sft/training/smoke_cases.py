"""A fixed set of records for reproducing adapter outputs.

ROADMAP 2.4 asks for 20 stable cases with at least five that offer only the
three knowledge tools. That floor is the point of the check: the platform
hands the router exactly those three, so an adapter that only behaves when
the full menu is present would fail the phase C integration while looking
healthy on the aggregate metrics.
"""

import argparse
import json
from pathlib import Path

from agent_toolcall_sft.data.records import DatasetRecord, write_records

KNOWLEDGE_TOOLS = frozenset(
    {"retrieval_tool", "summary_tool", "question_decompose_tool"}
)


def is_knowledge_only(record: DatasetRecord) -> bool:
    """True when this record offers nothing but the three knowledge tools."""
    return set(record.tools) <= KNOWLEDGE_TOOLS


def select_smoke_cases(
    records: list[DatasetRecord], size: int = 20, knowledge_only: int = 5
) -> list[DatasetRecord]:
    """Pick a deterministic case set that meets the knowledge-only floor."""
    if knowledge_only > size:
        raise ValueError(
            f"knowledge-only floor {knowledge_only} exceeds the case count {size}"
        )

    ordered = sorted(records, key=lambda r: r.id)
    knowledge = [r for r in ordered if is_knowledge_only(r)]
    if len(knowledge) < knowledge_only:
        raise ValueError(
            f"only {len(knowledge)} knowledge-only records, needs {knowledge_only}"
        )

    selected = knowledge[:knowledge_only]
    chosen = {r.id for r in selected}

    # Fill the remainder one family at a time. Taking the next ids in order
    # would hand back fifteen rows of a single family, which reproduces just
    # as deterministically but exercises far less of the router.
    families: dict[str, list[DatasetRecord]] = {}
    for record in ordered:
        if record.id not in chosen:
            families.setdefault(record.scenario_family, []).append(record)

    while len(selected) < size and families:
        for name in sorted(families):
            if len(selected) == size:
                break
            selected.append(families[name].pop(0))
            if not families[name]:
                del families[name]

    return sorted(selected[:size], key=lambda r: r.id)


def main() -> None:
    from agent_toolcall_sft.data.corpus import build_corpus, split_corpus

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--knowledge-only", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("artifacts/smoke_cases.jsonl"))
    args = parser.parse_args()

    cases = select_smoke_cases(
        split_corpus(build_corpus())["valid"], args.size, args.knowledge_only
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_records(args.out, cases)

    print(
        json.dumps(
            {
                "path": str(args.out),
                "cases": len(cases),
                "knowledge_only": sum(is_knowledge_only(r) for r in cases),
                "ids": [r.id for r in cases],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
