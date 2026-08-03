"""Paired bootstrap confidence intervals for a base-versus-adapter comparison.

Both models answer the same records, so the resampling draws *record indices*
and reads both sides at those indices. Sampling each side independently would
throw away the pairing and widen the interval with variance that the design
already removed -- the same records, the same prompt, the same decoding.

Reporting an interval this way is what lets the project claim a statistically
significant improvement instead of a bare percentage difference.
"""

import numpy as np

DEFAULT_ITERATIONS = 10_000
DEFAULT_SEED = 42
CONFIDENCE = 0.95


def paired_bootstrap(
    base: list[bool],
    tuned: list[bool],
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
) -> dict:
    """Bootstrap the paired difference `tuned - base` over shared records."""
    if len(base) != len(tuned):
        raise ValueError("base and tuned must have the same length")
    if not base:
        raise ValueError("need at least one record")

    left = np.asarray(base, dtype=float)
    right = np.asarray(tuned, dtype=float)
    n = left.size

    rng = np.random.default_rng(seed)
    # One index draw per iteration, applied to both sides: the pairing lives
    # here, and losing it is the classic way to overstate uncertainty.
    indices = rng.integers(0, n, size=(iterations, n))
    differences = (right[indices] - left[indices]).mean(axis=1)

    tail = (1 - CONFIDENCE) / 2 * 100
    low, high = np.percentile(differences, [tail, 100 - tail])

    return {
        "n": n,
        "base_rate": round(float(left.mean()), 6),
        "tuned_rate": round(float(right.mean()), 6),
        "difference": round(float(right.mean() - left.mean()), 6),
        "ci_low": round(float(low), 6),
        "ci_high": round(float(high), 6),
        "confidence": CONFIDENCE,
        "iterations": iterations,
        "seed": seed,
    }
