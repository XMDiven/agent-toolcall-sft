"""Tool-call and safety contracts for the customer-support routing model.

The three knowledge tools mirror rag-agent-platform's tool registry
(agent/src/agent_app/tools/registry.py) name-for-name so that a routing
decision produced here can be dispatched by that platform unchanged.
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

ORDER_ID_PATTERN = r"^ORD-\d{6}$"

RefundReason = Literal[
    "damaged_item",
    "wrong_item",
    "not_received",
    "quality_issue",
    "changed_mind",
]


class StrictModel(BaseModel):
    """Base model that rejects any field it does not declare."""

    model_config = ConfigDict(extra="forbid")


OrderId = Annotated[str, Field(pattern=ORDER_ID_PATTERN)]


# ---------------------------------------------------------------------------
# Knowledge tool arguments -- mirrored from rag-agent-platform's registry
# ---------------------------------------------------------------------------


class RetrievalToolArgs(StrictModel):
    question: str = Field(min_length=1)


class SummaryToolArgs(StrictModel):
    text: str = Field(min_length=1)


class QuestionDecomposeToolArgs(StrictModel):
    question: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Support tool arguments
# ---------------------------------------------------------------------------


class GetOrderStatusArgs(StrictModel):
    order_id: OrderId


class CheckRefundEligibilityArgs(StrictModel):
    order_id: OrderId
    reason: RefundReason


class CreateRefundRequestArgs(StrictModel):
    order_id: OrderId
    reason: RefundReason
    confirmed: Literal[True]


class CreateSupportTicketArgs(StrictModel):
    summary: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Tool calls, discriminated by tool name
# ---------------------------------------------------------------------------


class RetrievalToolCall(StrictModel):
    name: Literal["retrieval_tool"]
    arguments: RetrievalToolArgs


class SummaryToolCall(StrictModel):
    name: Literal["summary_tool"]
    arguments: SummaryToolArgs


class QuestionDecomposeToolCall(StrictModel):
    name: Literal["question_decompose_tool"]
    arguments: QuestionDecomposeToolArgs


class GetOrderStatusCall(StrictModel):
    name: Literal["get_order_status"]
    arguments: GetOrderStatusArgs


class CheckRefundEligibilityCall(StrictModel):
    name: Literal["check_refund_eligibility"]
    arguments: CheckRefundEligibilityArgs


class CreateRefundRequestCall(StrictModel):
    name: Literal["create_refund_request"]
    arguments: CreateRefundRequestArgs


class CreateSupportTicketCall(StrictModel):
    name: Literal["create_support_ticket"]
    arguments: CreateSupportTicketArgs


ToolCall = Annotated[
    RetrievalToolCall
    | SummaryToolCall
    | QuestionDecomposeToolCall
    | GetOrderStatusCall
    | CheckRefundEligibilityCall
    | CreateRefundRequestCall
    | CreateSupportTicketCall,
    Field(discriminator="name"),
]

KNOWLEDGE_TOOL_NAMES = frozenset(
    {"retrieval_tool", "summary_tool", "question_decompose_tool"}
)

def _tool_call_members() -> tuple[type[BaseModel], ...]:
    return get_args(get_args(ToolCall)[0])


def _discriminator_value(member: type[BaseModel]) -> str:
    return get_args(member.model_fields["name"].annotation)[0]


# Derived from the union rather than hand-listed, so a tool added above cannot
# be missed by the prompt renderer or by the name sets below.
TOOL_ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    _discriminator_value(member): member.model_fields["arguments"].annotation
    for member in _tool_call_members()
}

SUPPORT_TOOL_NAMES = frozenset(
    {
        "get_order_status",
        "check_refund_eligibility",
        "create_refund_request",
        "create_support_ticket",
    }
)

ALL_TOOL_NAMES = KNOWLEDGE_TOOL_NAMES | SUPPORT_TOOL_NAMES

WRITE_TOOL_NAMES = frozenset({"create_refund_request", "create_support_ticket"})

DANGEROUS_TOOL_NAMES = frozenset({"create_refund_request"})


# ---------------------------------------------------------------------------
# Decisions, discriminated by action
# ---------------------------------------------------------------------------


class ToolCallDecision(StrictModel):
    action: Literal["tool_call"]
    tool_call: ToolCall


class ClarifyDecision(StrictModel):
    action: Literal["clarify"]
    question: str = Field(min_length=1)


class DirectAnswerDecision(StrictModel):
    action: Literal["direct_answer"]
    answer: str = Field(min_length=1)


class HandoffDecision(StrictModel):
    action: Literal["handoff"]
    reason: str = Field(min_length=1)


Decision = Annotated[
    ToolCallDecision | ClarifyDecision | DirectAnswerDecision | HandoffDecision,
    Field(discriminator="action"),
]


# ---------------------------------------------------------------------------
# Single parsing entry point
# ---------------------------------------------------------------------------

_decision_adapter = TypeAdapter(Decision)


def parse_decision(raw: dict) -> Decision:
    """Parse a raw model output dict into a validated decision.

    Raises pydantic.ValidationError on anything that violates the contract,
    so callers never receive a partially valid decision.
    """
    return _decision_adapter.validate_python(raw)
