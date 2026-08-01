"""Machinery for turning rule-based scenario templates into dataset records.

Labels never come from an LLM: a template already knows the correct decision
for the sentence it just assembled. Every random choice is drawn from a
per-record seed, so any single record can be rebuilt from its provenance
without regenerating the whole split.

The templates themselves live in `agent_toolcall_sft.data.families`.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_toolcall_sft.contracts import ALL_TOOL_NAMES, KNOWLEDGE_TOOL_NAMES
from agent_toolcall_sft.data.records import DatasetRecord, Domain

TEMPLATE_VERSION = "v1"

# How many distractor tools are offered alongside the correct one. Keeping a
# range rather than a constant stops the model from learning "the answer is
# always the first tool in a list of four".
DISTRACTOR_RANGE = (1, 3)

# How many tools are offered to a record that should not call any tool.
IDLE_TOOL_RANGE = (2, 5)

# Share of records whose tool list is restricted to the three
# rag-agent-platform tools, exercising subset routing.
KNOWLEDGE_ONLY_RATIO = 0.5


@dataclass(frozen=True)
class RecordDraft:
    """The part of a record that a template decides."""

    messages: list[dict]
    tools: list[str]
    expected_decision: dict
    safety_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioFamily:
    """One template family: a named, domain-tagged record generator."""

    name: str
    domain: Domain
    draft: Callable[[random.Random], RecordDraft]


def offer_tools(
    rng: random.Random,
    required: str,
    pool: frozenset[str] = ALL_TOOL_NAMES,
) -> list[str]:
    """Build a shuffled tool list that always contains the required tool.

    The correct tool must be offered, otherwise the record would teach the
    model to call a tool it was never shown. Narrowing `pool` to the platform
    tools produces the subset-routing samples that ROADMAP 1.3 requires.
    """
    candidates = sorted(pool - {required})
    count = min(rng.randint(*DISTRACTOR_RANGE), len(candidates))
    tools = [required, *rng.sample(candidates, count)]
    rng.shuffle(tools)

    return tools


def offer_idle_tools(
    rng: random.Random,
    pool: frozenset[str] = ALL_TOOL_NAMES,
) -> list[str]:
    """Build a tool list for a record whose correct answer calls no tool.

    Tools are still offered: the model has to learn that having a tool
    available is not a reason to use it.
    """
    candidates = sorted(pool)
    count = min(rng.randint(*IDLE_TOOL_RANGE), len(candidates))

    return rng.sample(candidates, count)


def knowledge_only_pool(rng: random.Random) -> frozenset[str]:
    """Pick the tool pool for a record, sometimes restricting it.

    A share of samples offers only the three rag-agent-platform tools, so the
    model gets real training signal for the exact tool list the platform
    passes at inference time.
    """
    if rng.random() < KNOWLEDGE_ONLY_RATIO:
        return KNOWLEDGE_TOOL_NAMES

    return ALL_TOOL_NAMES


def synthetic_order_id(rng: random.Random) -> str:
    """Build a synthetic order id matching contracts.ORDER_ID_PATTERN."""
    return f"ORD-{rng.randint(100000, 999999)}"


def wrap(rng: random.Random, wrappers: tuple[str, ...], **parts: str) -> str:
    """Render one of several sentence skeletons.

    Several skeletons per family, never one: with a single skeleton the model
    can learn a positional shortcut instead of reading the sentence.
    """
    return rng.choice(wrappers).format(**parts)


def generate_family(
    family: ScenarioFamily, count: int, seed_base: int
) -> list[DatasetRecord]:
    """Generate `count` records for one family, one seed per record."""
    records: list[DatasetRecord] = []
    for index in range(count):
        seed = seed_base + index
        draft = family.draft(random.Random(seed))
        records.append(
            DatasetRecord(
                id=f"{family.name}_{index:06d}",
                scenario_family=family.name,
                domain=family.domain,
                messages=draft.messages,
                tools=draft.tools,
                expected_action=draft.expected_decision["action"],
                expected_decision=draft.expected_decision,
                safety_tags=draft.safety_tags,
                provenance={
                    "generator": "rule",
                    "template_version": TEMPLATE_VERSION,
                    "seed": seed,
                },
            )
        )

    return records
