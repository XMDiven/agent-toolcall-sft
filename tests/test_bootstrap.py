"""Paired bootstrap: the interval must reflect per-record pairing, not two samples."""

import pytest

from agent_toolcall_sft.evaluation.bootstrap import paired_bootstrap


def test_identical_outcomes_give_a_zero_width_interval():
    """The pairing test: resampling records, not sides, keeps every diff at 0."""
    outcomes = [True, False, True, True, False] * 20
    result = paired_bootstrap(outcomes, list(outcomes))

    assert result["difference"] == 0.0
    assert result["ci_low"] == 0.0
    assert result["ci_high"] == 0.0


def test_uniform_improvement_puts_the_lower_bound_above_zero():
    base = [False] * 100
    tuned = [True] * 100
    result = paired_bootstrap(base, tuned)

    assert result["base_rate"] == 0.0
    assert result["tuned_rate"] == 1.0
    assert result["difference"] == 1.0
    assert result["ci_low"] > 0


def test_a_nested_improvement_never_crosses_zero():
    """When no record regresses, every paired difference is >= 0 and so is the bound."""
    base = [True] * 48 + [False] * 52
    tuned = [True] * 50 + [False] * 50
    result = paired_bootstrap(base, tuned)

    assert result["difference"] == pytest.approx(0.02)
    assert result["ci_low"] >= 0


def test_a_small_gain_with_regressions_straddles_zero():
    base = [True] * 50 + [False] * 50
    tuned = [True] * 47 + [False] * 3 + [True] * 5 + [False] * 45
    result = paired_bootstrap(base, tuned)

    assert result["difference"] == pytest.approx(0.02)
    assert result["ci_low"] < 0 < result["ci_high"]


def test_same_seed_reproduces_the_interval():
    base = [i % 3 == 0 for i in range(200)]
    tuned = [i % 2 == 0 for i in range(200)]

    assert paired_bootstrap(base, tuned, seed=7) == paired_bootstrap(base, tuned, seed=7)


def test_mismatched_lengths_are_refused():
    with pytest.raises(ValueError, match="same length"):
        paired_bootstrap([True, False], [True])


def test_empty_input_is_refused():
    with pytest.raises(ValueError, match="at least one"):
        paired_bootstrap([], [])


def test_metadata_records_how_the_interval_was_made():
    result = paired_bootstrap([True, False], [True, True], iterations=500, seed=3)

    assert result["n"] == 2
    assert result["iterations"] == 500
    assert result["seed"] == 3
    assert result["confidence"] == 0.95
