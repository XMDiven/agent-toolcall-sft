"""The shipped QLoRA config must parse strictly and match the ROADMAP 2.1 values."""

import pytest
from pydantic import ValidationError

from agent_toolcall_sft.training.config import QLoRAConfig, load_config

CONFIG_PATH = "configs/qlora.yaml"


@pytest.fixture(scope="module")
def config() -> QLoRAConfig:
    return load_config(CONFIG_PATH)


def test_base_model_and_quantization(config):
    assert config.base_model == "Qwen/Qwen3-1.7B"
    assert config.quantization.load_in_4bit is True
    assert config.quantization.quant_type == "nf4"
    assert config.quantization.double_quant is True
    assert config.quantization.compute_dtype == "float16"


def test_lora_adapter_shape(config):
    assert (config.lora.r, config.lora.alpha, config.lora.dropout) == (16, 32, 0.05)
    assert config.lora.target_modules == [
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ]


def test_data_and_loss_scope(config):
    assert config.data.max_seq_length == 1024
    assert config.data.loss_on == "assistant"


def test_optimisation_budget(config):
    t = config.training
    assert (t.per_device_train_batch_size, t.gradient_accumulation_steps) == (1, 16)
    assert (t.num_train_epochs, t.learning_rate, t.warmup_ratio) == (2, 2e-4, 0.03)
    assert t.gradient_checkpointing is True
    assert t.seed == 42
    assert t.save_total_limit == 2
    assert t.eval_steps > 0 and t.save_steps > 0


def test_effective_batch_size_matches_the_6gb_budget(config):
    assert config.effective_batch_size == 16


def test_unknown_key_is_rejected(tmp_path):
    """A typo must fail loudly instead of silently falling back to a default."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "base_model: Qwen/Qwen3-1.7B\n"
        "quantization: {load_in_4bit: true, quant_type: nf4, double_quant: true,"
        " compute_dtype: float16}\n"
        "lora: {r: 16, alpha: 32, dropout: 0.05, target_modules: [q_proj],"
        " lora_alpha: 32}\n"
        "data: {max_seq_length: 1024, train_file: a, eval_file: b, loss_on: assistant}\n"
        "training: {per_device_train_batch_size: 1, gradient_accumulation_steps: 16,"
        " num_train_epochs: 2, learning_rate: 0.0002, warmup_ratio: 0.03,"
        " gradient_checkpointing: true, seed: 42, eval_steps: 50, save_steps: 50,"
        " save_total_limit: 2}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_config(bad)
