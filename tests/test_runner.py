"""Tests for the parts of the runner that do not need a GPU or a model."""

from agent_toolcall_sft.evaluation.run_baseline import (
    stride_sample,
    summarise_latency,
)
from agent_toolcall_sft.evaluation.runner import DECODING, DECODING_VERSION


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
