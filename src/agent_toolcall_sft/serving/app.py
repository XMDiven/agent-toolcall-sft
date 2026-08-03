"""HTTP router service over the fine-tuned model.

Every rejection returns 422 with a machine-readable `error`, never a decision.
A caller degrading to another backend needs to tell "the model produced
garbage" from "the model decided to hand off" — dressing a fault up as
`handoff` would have the caller escalate a request to a human because the JSON
was malformed.

Validation is `contracts.parse_decision` plus the offered-tool check, the same
rules the frozen evaluation scored against. A looser API would mean the
reported misuse rate no longer describes what ships.
"""

import json
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from agent_toolcall_sft.contracts import ALL_TOOL_NAMES, Decision, parse_decision
from agent_toolcall_sft.data.records import DatasetRecord
from agent_toolcall_sft.evaluation.parsing import extract_json_block
from agent_toolcall_sft.serving.backend import RouterBackend


class Message(BaseModel):
    role: str
    content: str


class RouteRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)
    tools: list[str] = Field(min_length=1)


class RouteResponse(BaseModel):
    decision: Decision
    model_version: str
    adapter_revision: str
    latency_ms: float


def _failure(error: str, detail: str, raw_output: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": error, "detail": detail, "raw_output": raw_output},
    )


def create_app(backend: RouterBackend, adapter: dict) -> FastAPI:
    app = FastAPI(title="agent-toolcall-sft router")

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "model_version": adapter["name"],
            "adapter_revision": adapter["revision"],
        }

    @app.post("/v1/route")
    def route(request: RouteRequest):
        unknown = sorted(set(request.tools) - set(ALL_TOOL_NAMES))
        if unknown:
            return _failure("unknown_tool_requested", f"未知工具：{unknown}", "")

        record = DatasetRecord(
            id="request",
            scenario_family="runtime",
            domain="support",
            template_key="runtime",
            messages=[m.model_dump() for m in request.messages],
            tools=request.tools,
            expected_action="clarify",
            expected_decision={"action": "clarify", "question": "占位"},
            safety_tags=[],
            provenance={"generator": "rule", "template_version": "runtime", "seed": 0},
        )

        started = time.perf_counter()
        raw = backend.generate(record)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        block = extract_json_block(raw)
        if block is None:
            return _failure("invalid_json", "输出中没有可解析的 JSON 对象", raw)
        try:
            payload = json.loads(block)
        except json.JSONDecodeError as error:
            return _failure("invalid_json", str(error), raw)

        try:
            decision = parse_decision(payload)
        except ValidationError as error:
            return _failure("schema_invalid", str(error), raw)

        call = getattr(decision, "tool_call", None)
        if call is not None and call.name not in request.tools:
            return _failure(
                "off_menu_tool", f"{call.name} 不在本次 tools 中", raw
            )

        return RouteResponse(
            decision=decision,
            model_version=adapter["name"],
            adapter_revision=adapter["revision"],
            latency_ms=latency_ms,
        )

    return app
