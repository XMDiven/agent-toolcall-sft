"""Tests for the parts of the runner that do not need a GPU or a model."""

import json
from types import SimpleNamespace

import pytest
from test_evaluation import make_record

from agent_toolcall_sft.evaluation.run_baseline import (
    build_parser,
    execute,
)
from agent_toolcall_sft.evaluation.runner import (
    DECODING,
    DECODING_VERSION,
    build_prompt,
    stride_sample,
    summarise_latency,
)


def test_decoding_is_deterministic():
    """Sampling would make the baseline unreproducible and the diff unusable."""
    assert DECODING.do_sample is False
    assert DECODING.num_beams == 1
    assert DECODING.enable_thinking is False
    assert DECODING_VERSION == "v1"


def test_latency_summary_reports_median_and_tail():
    summary = summarise_latency([100.0, 200.0, 300.0, 400.0, 5000.0])
    assert summary["p50_ms"] == 300.0
    assert summary["p95_ms"] == 400.0
    assert summary["mean_ms"] == 1200.0


def test_latency_summary_handles_a_single_sample():
    assert summarise_latency([42.0]) == {
        "p50_ms": 42.0,
        "p95_ms": 42.0,
        "mean_ms": 42.0,
    }


def test_stride_sample_spreads_across_the_split():
    """The first N records all share a family; a smoke test must not."""
    records = list(range(100))
    picked = stride_sample(records, 10)

    assert len(picked) == 10
    assert picked == [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]


def test_stride_sample_returns_everything_when_limit_exceeds_size():
    assert stride_sample([1, 2, 3], 10) == [1, 2, 3]


class RecordingTokenizer:
    def __init__(self):
        self.messages = None
        self.kwargs = None

    def apply_chat_template(self, messages, **kwargs):
        self.messages = messages
        self.kwargs = kwargs
        return "rendered"


def test_production_prompt_embeds_schema_without_native_tools_argument():
    tokenizer = RecordingTokenizer()
    record = make_record(tools=["get_order_status"])

    assert build_prompt(tokenizer, record) == "rendered"
    assert "tools" not in tokenizer.kwargs
    rendered = "\n".join(message["content"] for message in tokenizer.messages)
    assert "get_order_status" in rendered
    assert "查询指定订单" in rendered
    assert '"order_id"' in rendered
    assert '"action": "tool_call"' in rendered


def test_production_cli_reserves_and_verifies_before_model_load(
    tmp_path, monkeypatch
):
    split = tmp_path / "test.jsonl"
    split.write_text(make_record().model_dump_json() + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"splits": {"test": {"sha256": "0" * 64}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.run_baseline.load_model",
        lambda *_: pytest.fail("model loaded before manifest verification"),
    )
    args = SimpleNamespace(
        model="unused",
        split=split,
        manifest=manifest,
        limit=None,
        tag="new-tag",
        output_dir=tmp_path / "artifacts",
    )

    with pytest.raises(ValueError, match="does not match manifest"):
        execute(args)

    assert (args.output_dir / args.tag).is_dir()


def test_production_default_tag_names_the_protocol():
    assert build_parser().parse_args([]).tag == "production-json-v2"
