"""Join two frozen runs into one paired, per-record result.

The join is on `record_id` and refuses anything but an exact match on both
sides. A comparison built from two differently-ordered or differently-sized
runs would still produce a plausible-looking table, and the difference it
reported would not be the one the design intended to measure.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from agent_toolcall_sft.evaluation.scoring import RecordScore, is_fully_correct

_FIELDS = set(RecordScore.__dataclass_fields__)


def rebuild_score(payload: dict) -> RecordScore:
    """Reconstruct a RecordScore from its serialised form."""
    data = {key: value for key, value in payload.items() if key in _FIELDS}
    data["called_tools"] = tuple(data.get("called_tools") or ())

    return RecordScore(**data)


def read_predictions(directory: Path) -> list[dict]:
    path = directory / "predictions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def pair_records(base_rows: list[dict], tuned_rows: list[dict]) -> list[dict]:
    """Align two runs on record_id, refusing any mismatch."""
    base = {row["record_id"]: row for row in base_rows}
    tuned = {row["record_id"]: row for row in tuned_rows}
    if set(base) != set(tuned):
        raise ValueError("the two runs cover different records")

    paired = []
    for row in base_rows:
        record_id = row["record_id"]
        other = tuned[record_id]
        base_ok = is_fully_correct(rebuild_score(row["score"]))
        tuned_ok = is_fully_correct(rebuild_score(other["score"]))
        paired.append(
            {
                "record_id": record_id,
                "domain": row["domain"],
                "scenario_family": row["scenario_family"],
                "expected_action": row["score"]["expected_action"],
                "base_correct": base_ok,
                "tuned_correct": tuned_ok,
                "transition": (
                    "fixed" if tuned_ok and not base_ok
                    else "broken" if base_ok and not tuned_ok
                    else "both_correct" if base_ok
                    else "both_wrong"
                ),
                "base_output": row["raw_output"],
                "tuned_output": other["raw_output"],
                "base_json_ok": row["score"]["json_ok"],
                "tuned_json_ok": other["score"]["json_ok"],
            }
        )

    return paired


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--tuned", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    paired = pair_records(read_predictions(args.base), read_predictions(args.tuned))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in paired) + "\n",
        encoding="utf-8",
    )

    counts = Counter(row["transition"] for row in paired)
    print(json.dumps({"records": len(paired), "transitions": dict(counts)}, indent=2))


if __name__ == "__main__":
    main()
