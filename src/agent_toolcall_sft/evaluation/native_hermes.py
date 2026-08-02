"""Native Hermes auxiliary protocol for gold tool-call records only."""

from agent_toolcall_sft.contracts import TOOL_ARGUMENT_MODELS
from agent_toolcall_sft.data.records import DatasetRecord
from agent_toolcall_sft.evaluation.prompt import TOOL_DESCRIPTIONS

NATIVE_HERMES_PROMPT_VERSION = "native_hermes_v1"
NATIVE_SELECTION_RULE = 'expected_action == "tool_call"'

NATIVE_SYSTEM_PROMPT = """\
你是企业客服系统的工具路由助手。请从本次提供的工具中选择且只调用一个工具。
不得调用未提供的工具，不得臆造缺失参数。只输出原生工具调用。"""


def build_native_tool_specs(tool_names: list[str]) -> list[dict]:
    """Build the OpenAI function shape consumed by Hermes chat templates."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": TOOL_ARGUMENT_MODELS[name].model_json_schema(),
            },
        }
        for name in sorted(tool_names)
    ]


def render_native_messages(record: DatasetRecord) -> list[dict[str, str]]:
    turns = [{"role": "system", "content": NATIVE_SYSTEM_PROMPT}]
    turns.extend(
        {"role": message.role, "content": message.content}
        for message in record.messages
    )
    return turns


def build_native_prompt(tokenizer, record: DatasetRecord) -> str:
    return tokenizer.apply_chat_template(
        render_native_messages(record),
        tools=build_native_tool_specs(record.tools),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def select_native_records(records: list[DatasetRecord]) -> list[DatasetRecord]:
    """Keep only gold calls, preserving frozen split order."""
    return [record for record in records if record.expected_action == "tool_call"]
