"""Build the 4-bit base model with its LoRA adapter, and account for parameters.

The accounting is the point of ROADMAP 2.1's last item: if the adapter failed
to attach, training still runs and the loss still falls, but every weight moves
and the 6GB budget is gone. A ratio near 1.0 means the adapter is not there.
"""

import argparse
import json

from agent_toolcall_sft.training.config import QLoRAConfig, load_config

# A LoRA adapter on a 1.7B base sits far below this; anything above means the
# base weights are training too.
ADAPTER_RATIO_CEILING = 0.05


def describe_parameters(model) -> dict:
    """Count total and trainable parameters and judge whether only LoRA trains."""
    total = trainable = 0
    for parameter in model.parameters():
        count = parameter.numel()
        total += count
        if parameter.requires_grad:
            trainable += count

    ratio = trainable / total if total else 0.0

    return {
        "total": total,
        "trainable": trainable,
        "trainable_ratio": ratio,
        "adapter_only": 0 < ratio <= ADAPTER_RATIO_CEILING,
    }


def build_model(config: QLoRAConfig, model_path: str | None = None):
    """Load the quantized base model and attach the LoRA adapter."""
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    dtypes = {"float16": torch.float16, "bfloat16": torch.bfloat16}
    quantization = BitsAndBytesConfig(
        load_in_4bit=config.quantization.load_in_4bit,
        bnb_4bit_quant_type=config.quantization.quant_type,
        bnb_4bit_use_double_quant=config.quantization.double_quant,
        bnb_4bit_compute_dtype=dtypes[config.quantization.compute_dtype],
    )

    model = AutoModelForCausalLM.from_pretrained(
        model_path or config.base_model, quantization_config=quantization
    )
    model = prepare_model_for_kbit_training(
        model, use_gradient_checkpointing=config.training.gradient_checkpointing
    )

    return get_peft_model(
        model,
        LoraConfig(
            r=config.lora.r,
            lora_alpha=config.lora.alpha,
            lora_dropout=config.lora.dropout,
            target_modules=config.lora.target_modules,
            bias="none",
            task_type="CAUSAL_LM",
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/qlora.yaml")
    parser.add_argument("--model", default=None, help="local weights path")
    args = parser.parse_args()

    report = describe_parameters(build_model(load_config(args.config), args.model))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
