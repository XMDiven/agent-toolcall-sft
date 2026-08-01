"""Rule-based scenario templates that produce dataset records.

Labels never come from an LLM: a template already knows which tool call is
correct for the sentence it just assembled. Every random choice is drawn from
a per-record seed, so any single record can be rebuilt from its provenance
without regenerating the whole split.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_toolcall_sft.contracts import ALL_TOOL_NAMES, KNOWLEDGE_TOOL_NAMES
from agent_toolcall_sft.data.records import DatasetRecord, Domain, ExpectedAction

TEMPLATE_VERSION = "v1"

# How many distractor tools are offered alongside the correct one. Keeping a
# range rather than a constant stops the model from learning "the answer is
# always the first tool in a list of four".
DISTRACTOR_RANGE = (1, 3)

# Share of knowledge records whose tool list is restricted to the three
# rag-agent-platform tools.
KNOWLEDGE_ONLY_RATIO = 0.4


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


def knowledge_only_pool(rng: random.Random) -> frozenset[str]:
    """Pick the tool pool for a knowledge record.

    A share of knowledge samples offers only the three rag-agent-platform
    tools, so the model gets real training signal for the exact tool list the
    platform passes at inference time.
    """
    if rng.random() < KNOWLEDGE_ONLY_RATIO:
        return KNOWLEDGE_TOOL_NAMES

    return ALL_TOOL_NAMES


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


# ---------------------------------------------------------------------------
# Knowledge families
#
# Each of these embeds a verbatim core string inside a varying wrapper, and
# the expected argument is that core string unchanged. The model's job is to
# strip the wrapper, which keeps parameter exact-match a meaningful metric --
# scoring free-form paraphrase against a reference would not be.
# ---------------------------------------------------------------------------

_LOOKUP_QUESTIONS: tuple[str, ...] = (
    "你们的退货政策是什么",
    "保修期是多久",
    "发票怎么申请",
    "运费是怎么算的",
    "会员有哪些权益",
    "支持哪些支付方式",
    "换货流程是什么",
    "配送范围包括哪些地区",
    "预售商品什么时候发货",
    "优惠券怎么叠加使用",
    "退款一般多久到账",
    "商品支持七天无理由吗",
)

_LOOKUP_WRAPPERS: tuple[str, ...] = (
    "{core}？",
    "请问{core}？",
    "想咨询一下，{core}？",
    "你好，{core}？麻烦解答一下。",
)


def _draft_kb_lookup(rng: random.Random) -> RecordDraft:
    core = rng.choice(_LOOKUP_QUESTIONS)

    return RecordDraft(
        messages=[
            {"role": "user", "content": rng.choice(_LOOKUP_WRAPPERS).format(core=core)}
        ],
        tools=offer_tools(rng, "retrieval_tool", pool=knowledge_only_pool(rng)),
        expected_action="tool_call",
        expected_tool_call={
            "name": "retrieval_tool",
            "arguments": {"question": core},
        },
        safety_tags=["read_only"],
    )


KB_LOOKUP = ScenarioFamily(
    name="kb_lookup",
    domain="knowledge",
    draft=_draft_kb_lookup,
)


_COMPARE_QUESTIONS: tuple[str, ...] = (
    "标准版和专业版有什么区别",
    "顺丰和邮政的时效差多少",
    "会员和非会员的售后有什么不同",
    "线上下单和门店购买的保修一样吗",
    "预售和现货的发货时间差别在哪",
    "电子发票和纸质发票有什么区别",
    "以旧换新和直接购买哪个更划算",
    "年卡和月卡分别适合什么人",
)

_COMPARE_WRAPPERS: tuple[str, ...] = (
    "{core}？",
    "帮我对比一下，{core}？",
    "{core}？两个都说一下。",
    "我在纠结这两个，{core}？",
)


def _draft_kb_compare(rng: random.Random) -> RecordDraft:
    core = rng.choice(_COMPARE_QUESTIONS)

    return RecordDraft(
        messages=[
            {"role": "user", "content": rng.choice(_COMPARE_WRAPPERS).format(core=core)}
        ],
        tools=offer_tools(
            rng, "question_decompose_tool", pool=knowledge_only_pool(rng)
        ),
        expected_action="tool_call",
        expected_tool_call={
            "name": "question_decompose_tool",
            "arguments": {"question": core},
        },
        safety_tags=["read_only"],
    )


KB_COMPARE = ScenarioFamily(
    name="kb_compare",
    domain="knowledge",
    draft=_draft_kb_compare,
)


_SUMMARY_TEXTS: tuple[str, ...] = (
    (
        "本次活动自即日起至月底结束，全场满三百减五十，"
        "部分品类不参与，具体以商品页标注为准，优惠不与会员折扣叠加。"
    ),
    (
        "新版保修条款将人为损坏排除在免费维修范围外，"
        "自然故障仍享两年质保，延保服务需在购买后三十天内单独开通。"
    ),
    (
        "系统将于本周六凌晨两点至四点进行维护，"
        "期间下单和退款功能暂停，已提交的订单不受影响，维护完成后自动恢复。"
    ),
    (
        "会员积分规则调整为消费一元累积一分，积分有效期延长至两年，"
        "原有积分自动折算，兑换门槛从五百分下调至三百分。"
    ),
    (
        "跨境商品因清关流程较长，平均配送时间为七到十五个工作日，"
        "如遇海关抽检可能进一步延长，平台不承担由此产生的时效赔付。"
    ),
)

_SUMMARY_WRAPPERS: tuple[str, ...] = (
    "帮我总结一下这段：{core}",
    "这段太长了，能不能概括下重点：{core}",
    "{core}\n\n上面这段的核心意思是什么？",
    "麻烦提炼一下要点。原文：{core}",
)


def _draft_text_summarize(rng: random.Random) -> RecordDraft:
    core = rng.choice(_SUMMARY_TEXTS)

    return RecordDraft(
        messages=[
            {"role": "user", "content": rng.choice(_SUMMARY_WRAPPERS).format(core=core)}
        ],
        tools=offer_tools(rng, "summary_tool", pool=knowledge_only_pool(rng)),
        expected_action="tool_call",
        expected_tool_call={"name": "summary_tool", "arguments": {"text": core}},
        safety_tags=["read_only"],
    )


TEXT_SUMMARIZE = ScenarioFamily(
    name="text_summarize",
    domain="knowledge",
    draft=_draft_text_summarize,
)


KNOWLEDGE_FAMILIES: tuple[ScenarioFamily, ...] = (
    KB_LOOKUP,
    KB_COMPARE,
    TEXT_SUMMARIZE,
)
