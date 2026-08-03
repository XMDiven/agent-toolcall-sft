"""Parameter accounting must prove that only the adapter trains."""

import pytest

from agent_toolcall_sft.training.model import describe_parameters


class FakeParam:
    def __init__(self, n: int, trainable: bool):
        self._n = n
        self.requires_grad = trainable

    def numel(self) -> int:
        return self._n


class FakeModel:
    def __init__(self, params):
        self._params = params

    def parameters(self):
        return iter(self._params)


def test_counts_and_ratio():
    model = FakeModel([FakeParam(1_000_000, False), FakeParam(4_000, True)])
    report = describe_parameters(model)

    assert report["total"] == 1_004_000
    assert report["trainable"] == 4_000
    assert report["trainable_ratio"] == pytest.approx(4_000 / 1_004_000)


def test_all_frozen_is_reported_not_crashed():
    report = describe_parameters(FakeModel([FakeParam(10, False)]))
    assert report["trainable"] == 0
    assert report["trainable_ratio"] == 0.0


def test_a_fully_trainable_model_is_flagged():
    """Everything trainable means the adapter was not applied."""
    report = describe_parameters(FakeModel([FakeParam(10, True)]))
    assert report["trainable_ratio"] == 1.0
    assert report["adapter_only"] is False


def test_adapter_only_when_a_small_fraction_trains():
    report = describe_parameters(FakeModel([FakeParam(1_000_000, False), FakeParam(4_000, True)]))
    assert report["adapter_only"] is True
