"""The native Hermes auxiliary protocol stays separate from production JSON."""

import json
from types import SimpleNamespace

import pytest
from test_evaluation import make_record
from test_runner import RecordingTokenizer

from agent_toolcall_sft.data.corpus import _split_summary
from agent_toolcall_sft.evaluation.evidence import EvidenceExistsError
from agent_toolcall_sft.evaluation.native_hermes import (
    NATIVE_HERMES_PROMPT_VERSION,
    build_native_prompt,
    build_native_tool_specs,
    select_native_records,
)
from agent_toolcall_sft.evaluation.run_native_hermes_baseline import (
    build_parser,
    execute,
)
from agent_toolcall_sft.evaluation.runner import Generation
from agent_toolcall_sft.evaluation.scoring import native_auxiliary_metrics, score_record


def test_native_prompt_uses_chat_template_tools_argument():
    tokenizer = RecordingTokenizer()
    record = make_record(tools=["get_order_status"])

    assert build_native_prompt(tokenizer, record) == "rendered"
    assert tokenizer.kwargs["tools"][0]["function"]["name"] == "get_order_status"
    assert NATIVE_HERMES_PROMPT_VERSION == "native_hermes_v1"


def test_native_tool_specs_cover_only_offered_tools_in_stable_order():
    specs = build_native_tool_specs(["summary_tool", "get_order_status"])
    assert [spec["function"]["name"] for spec in specs] == [
        "get_order_status",
        "summary_tool",
    ]
    assert all(spec["type"] == "function" for spec in specs)
    assert "properties" in specs[0]["function"]["parameters"]


def test_native_selection_keeps_only_gold_tool_calls_in_order():
    tool_a = make_record(id="a")
    non_tool = make_record(
        id="b",
        expected_action="clarify",
        expected_decision={"action": "clarify", "question": "请补充信息。"},
    )
    tool_c = make_record(id="c")

    selected = select_native_records([tool_a, non_tool, tool_c])

    assert [record.id for record in selected] == ["a", "c"]


def test_native_metrics_do_not_publish_main_behavior_accuracy():
    score = score_record(make_record(), "not json")
    metrics = native_auxiliary_metrics([score])

    assert metrics["n"] == 1
    assert "behavior_accuracy" not in metrics
    assert "end_to_end_accuracy" not in metrics
    assert "action_accuracy" not in metrics


def test_native_default_tag_cannot_be_confused_with_production():
    assert build_parser().parse_args([]).tag == "native-hermes-v1"


def _native_args(tmp_path, records, *, tag="native", limit=None, valid=True):
    split = tmp_path / f"{tag}-test.jsonl"
    split.write_text(
        "".join(record.model_dump_json() + "\n" for record in records),
        encoding="utf-8",
    )
    summary = _split_summary(records)
    if not valid:
        summary = {**summary, "sha256": "0" * 64}
    manifest = tmp_path / f"{tag}-manifest.json"
    manifest.write_text(
        json.dumps({"splits": {"test": summary}}), encoding="utf-8"
    )
    return SimpleNamespace(
        model="remote/model",
        split=split,
        manifest=manifest,
        limit=limit,
        tag=tag,
        output_dir=tmp_path / "artifacts",
    )


def test_native_execute_selects_gold_calls_before_applying_limit(
    tmp_path, monkeypatch
):
    non_tool = make_record(
        id="first-non-tool",
        expected_action="clarify",
        expected_decision={"action": "clarify", "question": "请补充。"},
    )
    tool_a = make_record(id="second-tool")
    tool_b = make_record(id="third-tool")
    args = _native_args(tmp_path, [non_tool, tool_a, tool_b], limit=1)
    seen = {}

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda model: ("model", "tokenizer"),
    )

    def fake_run(model, tokenizer, records, *, prompt_builder):
        seen["ids"] = [record.id for record in records]
        assert prompt_builder is build_native_prompt
        return [Generation(records[0].id, "not json", 12.5, 20, 3)]

    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.run_split", fake_run
    )
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.environment_fingerprint",
        lambda model, prompt_version: {"gpu": "fake", "peak_vram_gib": 1.25},
    )

    destination = execute(args)
    summary = json.loads((destination / "summary.json").read_text())

    assert seen["ids"] == ["second-tool"]
    assert summary["selection_rule"] == 'expected_action == "tool_call"'
    assert summary["source_records"] == 3
    assert summary["selected_records"] == 2
    assert summary["evaluated_records"] == 1
    assert set(summary["latency"]) == {"p50_ms", "p95_ms", "mean_ms"}
    assert set(summary["tokens"]) == {"prompt_mean", "completion_mean"}
    assert "schema_valid_rate" in summary["auxiliary_metrics"]
    assert "behavior_accuracy" not in summary["auxiliary_metrics"]


def test_native_execute_rejects_existing_destination_before_model_load(
    tmp_path, monkeypatch
):
    args = _native_args(tmp_path, [make_record()])
    (args.output_dir / args.tag).mkdir(parents=True)
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda model: pytest.fail("model must not load for an existing tag"),
    )

    with pytest.raises(EvidenceExistsError, match="different --tag"):
        execute(args)


def test_native_execute_manifest_mismatch_loads_no_model_and_reserves_no_tag(
    tmp_path, monkeypatch
):
    args = _native_args(tmp_path, [make_record()], valid=False)
    monkeypatch.setattr(
        "agent_toolcall_sft.evaluation.evidence.load_model",
        lambda model: pytest.fail("model must not load for manifest mismatch"),
    )

    with pytest.raises(ValueError, match="does not match manifest"):
        execute(args)

    assert not (args.output_dir / args.tag).exists()
