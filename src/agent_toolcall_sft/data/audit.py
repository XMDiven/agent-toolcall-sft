"""Stratified sampling for the manual data audit.

The sheet this produces is a worksheet for a *second* reviewer, not the record
of an audit already performed. An unticked sheet means nobody has independently
read the rows yet; it does not mean the corpus went unchecked. What the project
has already run over every row lives in `reports/data_audit_v2.md`.

The audit reads training data only. Every split comes out of the same
templates, so the training split is fully representative -- and never opening
the test set removes any chance of a rule being rewritten because of what the
held-out answers happened to look like.
"""

import random
from collections import Counter, defaultdict

from agent_toolcall_sft.data.records import DatasetRecord

AUDIT_SIZE = 60
AUDIT_SEED = 20260801

# ROADMAP 1.4 floors: the safety and knowledge strata each carry at least 15
# rows regardless of how small they are in the corpus.
FLOOR_QUOTAS: dict[str, int] = {"safety": 15, "knowledge": 15}


def stratum_of(record: DatasetRecord) -> str:
    """Bucket a record by what an auditor would judge it on."""
    if "high_risk" in record.safety_tags:
        return "safety"
    if record.domain == "knowledge":
        return "knowledge"

    return f"support:{record.expected_action}"


def _remaining_quotas(pools: dict[str, list], budget: int) -> dict[str, int]:
    """Split the leftover budget across strata by size, largest remainder."""
    sizes = {name: len(rows) for name, rows in pools.items()}
    total = sum(sizes.values())
    exact = {name: size * budget / total for name, size in sizes.items()}
    quotas = {name: int(value) for name, value in exact.items()}

    leftover = budget - sum(quotas.values())
    order = sorted(pools, key=lambda name: (-(exact[name] - quotas[name]), name))
    for name in order[:leftover]:
        quotas[name] += 1

    return quotas


def sample_for_audit(
    records: list[DatasetRecord], size: int = AUDIT_SIZE, seed: int = AUDIT_SEED
) -> list[DatasetRecord]:
    """Draw a stratified audit sample covering every behaviour and domain."""
    pools: dict[str, list[DatasetRecord]] = defaultdict(list)
    for record in records:
        pools[stratum_of(record)].append(record)

    quotas = dict(FLOOR_QUOTAS)
    for name, quota in quotas.items():
        if len(pools.get(name, [])) < quota:
            raise ValueError(f"stratum {name} holds fewer than {quota} records")

    rest = {name: rows for name, rows in pools.items() if name not in quotas}
    quotas.update(_remaining_quotas(rest, size - sum(quotas.values())))

    sample: list[DatasetRecord] = []
    for name in sorted(quotas):
        sample.extend(
            _sample_distinct_templates(
                pools[name], quotas[name], f"{seed}:{name}"
            )
        )

    expected_strata = Counter(map(stratum_of, sample))
    sample = _supplement_safety_tags(sample, records, size, expected_strata)
    sample = sorted(sample, key=lambda record: (stratum_of(record), record.id))
    _assert_postconditions(sample, records, size, expected_strata)
    return sample


def _safety_tags(records: list[DatasetRecord]) -> set[str]:
    return {tag for record in records for tag in record.safety_tags}


def _meets_structure(
    sample: list[DatasetRecord], size: int, expected_strata: Counter[str]
) -> bool:
    counts = Counter(stratum_of(record) for record in sample)
    return (
        len(sample) == size
        and len({record.id for record in sample}) == size
        and len({record.template_key for record in sample}) == size
        and counts == expected_strata
        and counts["safety"] >= FLOOR_QUOTAS["safety"]
        and counts["knowledge"] >= FLOOR_QUOTAS["knowledge"]
        and {record.domain for record in sample} == {"knowledge", "support"}
        and {record.expected_action for record in sample}
        == {"tool_call", "clarify", "direct_answer", "handoff"}
    )


def _supplement_safety_tags(
    sample: list[DatasetRecord],
    records: list[DatasetRecord],
    size: int,
    expected_strata: Counter[str],
) -> list[DatasetRecord]:
    """Find deterministic same-stratum swaps covering all population tags."""
    population_tags = _safety_tags(records)

    def candidates_for(tag: str, current: list[DatasetRecord]):
        current_ids = {record.id for record in current}
        return sorted(
            (
                record
                for record in records
                if tag in record.safety_tags and record.id not in current_ids
            ),
            key=lambda record: (record.template_key, record.id),
        )

    def search(current: list[DatasetRecord]) -> list[DatasetRecord] | None:
        covered_tags = _safety_tags(current)
        missing_tags = population_tags - covered_tags
        if not missing_tags:
            return current

        missing_tag = min(
            missing_tags,
            key=lambda tag: (len(candidates_for(tag, current)), tag),
        )
        for candidate in candidates_for(missing_tag, current):
            replacements = sorted(
                (
                    (index, record)
                    for index, record in enumerate(current)
                    if stratum_of(record) == stratum_of(candidate)
                ),
                key=lambda item: item[1].id,
            )
            for index, _ in replacements:
                trial = [*current]
                trial[index] = candidate
                if not _meets_structure(trial, size, expected_strata):
                    continue
                if not covered_tags <= _safety_tags(trial):
                    continue

                result = search(trial)
                if result is not None:
                    return result

        return None

    result = search(sample)
    if result is None:
        missing_tags = sorted(population_tags - _safety_tags(sample))
        raise ValueError(
            f"cannot cover safety tags {missing_tags} without violating "
            "audit postconditions"
        )

    return result


def _assert_postconditions(
    sample: list[DatasetRecord],
    records: list[DatasetRecord],
    size: int,
    expected_strata: Counter[str],
) -> None:
    """Fail closed if the deterministic audit contract is not satisfied."""
    if not _meets_structure(sample, size, expected_strata):
        raise ValueError("audit sample violates size, diversity, or floor constraints")

    missing_tags = sorted(_safety_tags(records) - _safety_tags(sample))
    if missing_tags:
        raise ValueError(f"audit sample is missing safety tags: {missing_tags}")


def _sample_distinct_templates(
    rows: list[DatasetRecord], quota: int, seed: str
) -> list[DatasetRecord]:
    """Draw one row per template first, so the budget is not spent twice.

    Two rows built from the same template differ only in their wrapper; an
    auditor reading both learns nothing the first one did not already show.
    """
    by_template: dict[str, list[DatasetRecord]] = defaultdict(list)
    for row in sorted(rows, key=lambda record: record.id):
        by_template[row.template_key].append(row)

    rng = random.Random(seed)
    keys = sorted(by_template)
    rng.shuffle(keys)

    picked = [by_template[key][0] for key in keys[:quota]]
    if len(picked) < quota:
        leftovers = [
            row
            for key in keys
            for row in by_template[key][1:]
        ]
        picked.extend(rng.sample(leftovers, quota - len(picked)))

    return picked


def _expected_summary(record: DatasetRecord) -> str:
    decision = record.expected_decision
    if decision.action == "tool_call":
        arguments = decision.tool_call.arguments.model_dump()
        return f"`{decision.tool_call.name}` {arguments}"

    text = getattr(decision, "question", None) or getattr(decision, "answer", None)
    return f"`{decision.action}` — {text or decision.reason}"


def render_audit_sheet(records: list[DatasetRecord]) -> str:
    """Render the sample as a checklist an auditor can mark up in place."""
    counts = Counter(stratum_of(record) for record in records)
    lines = [
        "# 数据人工审计工作表",
        "",
        (
            "> 这是一份**待审工作表**，供项目所有者独立复核。空的勾选框表示"
            "尚无第二人复核，不代表语料未经检查——已执行的全量检查见 "
            "`reports/data_audit_v2.md`。"
        ),
        "",
        f"样本量：{len(records)} 条，来源：train + valid（**不含 test**）",
        "",
        "## 分层构成",
        "",
        "| 层 | 条数 |",
        "| --- | ---: |",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(counts.items()))
    lines.extend(
        [
            "",
            "## 怎么审",
            "",
            "逐条问自己四个问题，有问题就在该条下面写一行：",
            "",
            "1. **标签对吗** — 如果我是客服，我会这么做吗？",
            "2. **句子像人话吗** — 念一遍，别扭就记下来。",
            "3. **工具清单合理吗** — 正确答案的工具在不在清单里？干扰项离谱吗？",
            "4. **有没有真实个人信息** — 姓名、地址、电话。",
            "",
            "发现问题按四类标注：",
            "",
            "- `label` 标准答案错了 → 改规则，整族重新生成",
            "- `template` 句子生成得不对或不自然 → 改模板",
            "- `drift` 语义被改写破坏 → 收紧改写",
            "- `policy` 这个场景本来就有争议 → 不改，写进报告的已知边界",
            "",
            "---",
            "",
        ]
    )

    current = None
    for index, record in enumerate(records, start=1):
        stratum = stratum_of(record)
        if stratum != current:
            lines.extend([f"## {stratum}", ""])
            current = stratum

        content = record.messages[0].content.replace("\n", " ⏎ ")
        lines.extend(
            [
                f"### {index}. `{record.id}`",
                "",
                f"- 用户：{content}",
                f"- 标准答案：{_expected_summary(record)}",
                f"- 可用工具：{record.tools}",
                f"- 安全标签：{record.safety_tags or '—'}",
                f"- 模板键：`{record.template_key}`",
                "- [ ] 通过",
                "- 问题：",
                "",
            ]
        )

    return "\n".join(lines)
