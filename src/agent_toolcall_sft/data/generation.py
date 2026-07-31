"""Rule-based scenario templates that produce dataset records.

Labels never come from an LLM: a template already knows which tool call is
correct for the sentence it just assembled. Every random choice is drawn from
a per-record seed, so any single record can be rebuilt from its provenance
without regenerating the whole split.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_toolcall_sft.contracts import ALL_TOOL_NAMES
from agent_toolcall_sft.data.records import DatasetRecord, Domain, ExpectedAction

TEMPLATE_VERSION = "v1"

# How many distractor tools are offered alongside the correct one. Keeping a
# range rather than a constant stops the model from learning "the answer is
# always the first tool in a list of four".
DISTRACTOR_RANGE = (1, 3)


@dataclass(frozen=True)
class RecordDraft:
    """The part of a record that a template decides."""

    messages: list[dict]
    tools: list[str]
    expected_action: ExpectedAction
    expected_tool_call: dict | None = None
    safety_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioFamily:
    """One template family: a named, domain-tagged record generator."""

    name: str
    domain: Domain
    draft: Callable[[random.Random], RecordDraft]


def offer_tools(rng: random.Random, required: str) -> list[str]:
    """Build a shuffled tool list that always contains the required tool.

    The correct tool must be offered, otherwise the record would teach the
    model to call a tool it was never shown.
    """
    candidates = sorted(ALL_TOOL_NAMES - {required})
    distractors = rng.sample(candidates, rng.randint(*DISTRACTOR_RANGE))
    tools = [required, *distractors]
    rng.shuffle(tools)

    return tools


def synthetic_order_id(rng: random.Random) -> str:
    """Build a synthetic order id matching contracts.ORDER_ID_PATTERN."""
    return f"ORD-{rng.randint(100000, 999999)}"


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
                expected_action=draft.expected_action,
                expected_tool_call=draft.expected_tool_call,
                safety_tags=draft.safety_tags,
                provenance={
                    "generator": "rule",
                    "template_version": TEMPLATE_VERSION,
                    "seed": seed,
                },
            )
        )

    return records


# ---------------------------------------------------------------------------
# Family: refund_confirmed
# The user names an order, states a valid reason, and explicitly confirms.
# This is the only situation where create_refund_request is the right answer.
# ---------------------------------------------------------------------------

_REFUND_COMPLAINTS: dict[str, tuple[str, ...]] = {
    "damaged_item": ("收到时外包装破损", "拆开发现商品摔坏了", "到货就是碎的"),
    "wrong_item": ("发来的型号不对", "收到的不是我下单的那件", "颜色发错了"),
    "quality_issue": ("用了两天就出问题", "做工有明显瑕疵", "刚拆封就无法开机"),
    "not_received": ("显示签收了但我没收到", "物流停了半个月还没到"),
}

_CONFIRMATIONS: tuple[str, ...] = (
    "我确认要退款",
    "确认退款，麻烦处理",
    "我确定要退，请帮我提交",
)

# Several skeletons per family, not one. With a single skeleton the model can
# learn a positional shortcut ("the order id is always the fifth character")
# instead of learning to read the sentence.
_REFUND_SENTENCES: tuple[str, ...] = (
    "我的订单 {order_id} {complaint}，{confirmation}。",
    "{confirmation}。订单号是 {order_id}，{complaint}。",
    "{complaint}，订单是 {order_id}。{confirmation}。",
    "订单 {order_id} 有问题：{complaint}。{confirmation}，谢谢。",
)


def _draft_refund_confirmed(rng: random.Random) -> RecordDraft:
    order_id = synthetic_order_id(rng)
    reason = rng.choice(sorted(_REFUND_COMPLAINTS))
    sentence = rng.choice(_REFUND_SENTENCES).format(
        order_id=order_id,
        complaint=rng.choice(_REFUND_COMPLAINTS[reason]),
        confirmation=rng.choice(_CONFIRMATIONS),
    )

    return RecordDraft(
        messages=[{"role": "user", "content": sentence}],
        tools=offer_tools(rng, required="create_refund_request"),
        expected_action="tool_call",
        expected_tool_call={
            "name": "create_refund_request",
            "arguments": {
                "order_id": order_id,
                "reason": reason,
                "confirmed": True,
            },
        },
        safety_tags=["write_tool", "explicit_confirmation"],
    )


REFUND_CONFIRMED = ScenarioFamily(
    name="refund_confirmed",
    domain="support",
    draft=_draft_refund_confirmed,
)
