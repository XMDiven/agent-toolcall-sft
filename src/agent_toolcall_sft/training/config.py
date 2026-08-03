"""Typed loader for the QLoRA training configuration.

A YAML file is silent about typos: writing `lora_alpha` where `alpha` is
expected leaves the intended value unused and the run still starts, burning
GPU time under settings nobody chose. Parsing through `extra="forbid"` turns
that into a failure before the first step.

The config is also the hashable record of what a run used -- ROADMAP 2.4
stores its digest alongside the commit and the data manifest.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Reject unknown keys so a mistyped setting cannot pass silently."""

    model_config = ConfigDict(extra="forbid")


class QuantizationConfig(StrictModel):
    load_in_4bit: bool
    quant_type: Literal["nf4", "fp4"]
    double_quant: bool
    compute_dtype: Literal["float16", "bfloat16"]


class LoRAConfig(StrictModel):
    r: int = Field(gt=0)
    alpha: int = Field(gt=0)
    dropout: float = Field(ge=0.0, lt=1.0)
    target_modules: list[str] = Field(min_length=1)


class DataConfig(StrictModel):
    train_file: str
    eval_file: str
    max_seq_length: int = Field(gt=0)
    loss_on: Literal["assistant"]


class TrainingConfig(StrictModel):
    per_device_train_batch_size: int = Field(gt=0)
    gradient_accumulation_steps: int = Field(gt=0)
    num_train_epochs: int = Field(gt=0)
    learning_rate: float = Field(gt=0.0)
    warmup_ratio: float = Field(ge=0.0, lt=1.0)
    gradient_checkpointing: bool
    seed: int
    eval_steps: int = Field(gt=0)
    save_steps: int = Field(gt=0)
    save_total_limit: int = Field(gt=0)


class QLoRAConfig(StrictModel):
    base_model: str
    quantization: QuantizationConfig
    lora: LoRAConfig
    data: DataConfig
    training: TrainingConfig

    @property
    def effective_batch_size(self) -> int:
        """What the optimiser actually sees per step on a single 6GB device."""
        return (
            self.training.per_device_train_batch_size
            * self.training.gradient_accumulation_steps
        )


def load_config(path: str | Path) -> QLoRAConfig:
    """Parse and validate the training config at `path`."""
    return QLoRAConfig.model_validate(
        yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    )
