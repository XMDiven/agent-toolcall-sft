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

# v2 expanded every content pool ~2.5x and gave order_status_lookup a
# stable template_key; v1 splits are not comparable and are kept only as
# historical evidence.
TEMPLATE_VERSION = "v2"

# How many distractor tools are offered alongside the correct one. Keeping a
# range rather than a constant stops the model from learning "the answer is
# always the first tool in a list of four".
DISTRACTOR_RANGE = (1, 3)

# How many tools are offered to a record that should not call any tool.
IDLE_TOOL_RANGE = (2, 5)

# Share of records whose tool list is restricted to the three
# rag-agent-platform tools, exercising subset routing.
KNOWLEDGE_ONLY_RATIO = 0.5

# How many draws per requested record before a family is declared too narrow.
UNIQUENESS_ATTEMPT_FACTOR = 60


@dataclass(frozen=True)
class RecordDraft:
    """The part of a record that a template decides."""

    messages: list[dict]
    tools: list[str]
    expected_decision: dict
    safety_tags: list[str] = field(default_factory=list)
    template_key: str | None = None
    """Identifies the reusable content this record was built from.

    Splitting holds whole template keys together, so a phrasing the model
    trained on can never reappear in the test set wearing a different
    wrapper. Leave it None when nothing in the record repeats across records
    -- a randomised order id makes every sentence genuinely new, and pinning
    such records into shared groups would only coarsen the split for nothing.
    """


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


def template_key(family: str, core: str, limit: int = 40) -> str:
    """Build a readable grouping key from a family name and its content core."""
    return f"{family}:{core[:limit]}"


def synthetic_order_id(rng: random.Random) -> str:
    """Build a synthetic order id matching contracts.ORDER_ID_PATTERN."""
    return f"ORD-{rng.randint(100000, 999999)}"


def wrap(rng: random.Random, wrappers: tuple[str, ...], **parts: str) -> str:
    """Render one of several sentence skeletons.

    Several skeletons per family, never one: with a single skeleton the model
    can learn a positional shortcut instead of reading the sentence.
    """
    return rng.choice(wrappers).format(**parts)


def compose(
    rng: random.Random,
    core: str,
    openers: tuple[str, ...],
    closers: tuple[str, ...],
) -> str:
    """Surround a core utterance with an optional opener and closer.

    Short utterances such as greetings have few natural phrasings. Composing
    independent particles multiplies the reachable sentences instead of
    forcing the same handful of lines to repeat dozens of times.
    """
    return f"{rng.choice(openers)}{core}{rng.choice(closers)}"


class InsufficientVariety(RuntimeError):
    """A family cannot fill its quota with distinct user messages.

    Raised instead of silently emitting duplicates: near-identical rows break
    the independence assumption behind the bootstrap confidence interval, so
    a quota a family cannot honestly fill has to fail loudly.
    """


def generate_family(
    family: ScenarioFamily, count: int, seed_base: int
) -> list[DatasetRecord]:
    """Generate `count` records with distinct user messages.

    Each record is built from its own seed, salted with the family name so
    two families never draw the same random stream -- without the salt every
    family emits the same synthetic order ids in the same order.
    """
    records: list[DatasetRecord] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    attempt_limit = count * UNIQUENESS_ATTEMPT_FACTOR
    seed = seed_base

    while len(records) < count:
        if seed - seed_base >= attempt_limit:
            raise InsufficientVariety(
                f"{family.name} yielded only {len(records)} distinct messages "
                f"of the {count} requested; add templates or lower the quota"
            )

        draft = family.draft(random.Random(f"{family.name}:{seed}"))
        key = tuple((m["role"], m["content"]) for m in draft.messages)
        current_seed = seed
        seed += 1

        if key in seen:
            continue
        seen.add(key)

        record_id = f"{family.name}_{len(records):06d}"
        records.append(
            DatasetRecord(
                id=record_id,
                scenario_family=family.name,
                template_key=draft.template_key or record_id,
                domain=family.domain,
                messages=draft.messages,
                tools=draft.tools,
                expected_action=draft.expected_decision["action"],
                expected_decision=draft.expected_decision,
                safety_tags=draft.safety_tags,
                provenance={
                    "generator": "rule",
                    "template_version": TEMPLATE_VERSION,
                    "seed": current_seed,
                },
            )
        )

    return records
