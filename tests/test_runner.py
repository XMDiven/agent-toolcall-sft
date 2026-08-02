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
    load_model,
    stride_sample,
    summarise_latency,
)


@pytest.fixture(autouse=True)
def _clean_worktree(monkeypatch):
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence._git_status_porcelain",
        lambda: "",
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


def test_load_model_pins_tokenizer_and_model_to_same_revision(monkeypatch):
    from agent_toolcall_sft.evaluation import runner

    seen = {}

    class FakeModel:
        def eval(self):
            seen["eval"] = True

    def fake_tokenizer(model_id, **kwargs):
        seen["tokenizer"] = (model_id, kwargs)
        return "tokenizer"

    def fake_model(model_id, **kwargs):
        seen["model"] = (model_id, kwargs)
        return FakeModel()

    monkeypatch.setattr(runner.AutoTokenizer, "from_pretrained", fake_tokenizer)
    monkeypatch.setattr(
        runner.AutoModelForCausalLM, "from_pretrained", fake_model
    )

    _model, tokenizer = load_model("remote/model", revision="A" * 40)

    assert tokenizer == "tokenizer"
    assert seen["tokenizer"] == ("remote/model", {"revision": "A" * 40})
    assert seen["model"][0] == "remote/model"
    assert seen["model"][1]["revision"] == "A" * 40
    assert seen["eval"] is True


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
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda *_: pytest.fail("model loaded before manifest verification"),
    )
    args = SimpleNamespace(
        model="unused",
        revision="a" * 40,
        split=split,
        manifest=manifest,
        limit=None,
        tag="new-tag",
        output_dir=tmp_path / "artifacts",
    )

    with pytest.raises(ValueError, match="does not match manifest"):
        execute(args)

    assert not (args.output_dir / args.tag).exists()


def test_production_default_tag_names_the_protocol():
    args = build_parser().parse_args([])
    assert args.tag == "production-json-v2"
    assert args.revision is None


@pytest.mark.parametrize("limit", ["0", "-1"])
def test_production_cli_rejects_non_positive_limit(limit):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--limit", limit])


def test_production_formal_tag_rejects_limit_before_model_load_or_directory(
    tmp_path, monkeypatch
):
    records = [make_record()]
    split = tmp_path / "test.jsonl"
    split.write_text(records[0].model_dump_json() + "\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    from agent_toolcall_sft.data.corpus import _split_summary

    manifest.write_text(
        json.dumps({"splits": {"test": _split_summary(records)}}),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        model="remote/model",
        revision="a" * 40,
        split=split,
        manifest=manifest,
        limit=1,
        tag="production-json-v2",
        output_dir=tmp_path / "artifacts",
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda *_args, **_kwargs: pytest.fail("formal limited run must not load"),
    )

    with pytest.raises(ValueError, match="different --tag"):
        execute(args)

    assert not (args.output_dir / args.tag).exists()


def test_dirty_worktree_rejected_before_model_load_or_directory(
    tmp_path, monkeypatch
):
    args = SimpleNamespace(
        model="remote/model",
        revision="a" * 40,
        split=tmp_path / "not-read.jsonl",
        manifest=tmp_path / "not-read.json",
        limit=None,
        tag="dirty-run",
        output_dir=tmp_path / "artifacts",
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence._git_status_porcelain",
        lambda: " M tracked.py\n?? new.txt\n",
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda *_args, **_kwargs: pytest.fail("dirty run must not load model"),
    )

    with pytest.raises(RuntimeError, match="worktree must be clean"):
        execute(args)

    assert not (args.output_dir / args.tag).exists()
