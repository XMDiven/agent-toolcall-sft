"""Run QLoRA fine-tuning from a validated config.

The run refuses to continue on a non-finite loss. A NaN that is merely logged
produces a checkpoint that looks finished and has learned nothing, and the
cost of noticing later is a full evaluation cycle.
"""

import argparse
import json
import math
import time
from pathlib import Path

from agent_toolcall_sft.data.records import read_records
from agent_toolcall_sft.training.config import QLoRAConfig, load_config
from agent_toolcall_sft.training.data import build_examples, collate
from agent_toolcall_sft.training.model import build_model, describe_parameters
from agent_toolcall_sft.training.provenance import capture_provenance


class _Dataset:
    def __init__(self, examples):
        self._examples = examples

    def __len__(self):
        return len(self._examples)

    def __getitem__(self, index):
        return self._examples[index]


def _collator(pad_token_id):
    import torch

    def call(batch):
        padded = collate(batch, pad_token_id)
        return {key: torch.tensor(value) for key, value in padded.items()}

    return call


def _abort_on_non_finite_loss():
    from transformers import TrainerCallback

    class Guard(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            loss = (logs or {}).get("loss")
            if loss is not None and not math.isfinite(loss):
                raise RuntimeError(f"non-finite loss at step {state.global_step}")

    return Guard()


def resolve_data_files(args, config: QLoRAConfig) -> tuple[Path, Path]:
    """Pick the train/eval files, CLI first, and hand back real paths."""
    return (
        Path(args.train_file or config.data.train_file),
        Path(args.eval_file or config.data.eval_file),
    )


def run(args, config: QLoRAConfig) -> dict:
    import torch
    from transformers import AutoTokenizer, Trainer, TrainingArguments

    tokenizer = AutoTokenizer.from_pretrained(args.model or config.base_model)
    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None:
        pad_token_id = tokenizer.eos_token_id

    train_file, eval_file = resolve_data_files(args, config)

    # Written before the model is even loaded: a record produced afterwards
    # would describe whatever the tree looked like when the run ended.
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = capture_provenance(
        args.config, args.manifest, train_file, eval_file, args.model or config.base_model
    )
    (output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    train = build_examples(
        tokenizer,
        read_records(train_file),
        config.data.max_seq_length,
        args.max_train_samples,
    )
    evaluation = build_examples(
        tokenizer,
        read_records(eval_file),
        config.data.max_seq_length,
        args.max_eval_samples,
    )

    model = build_model(config, args.model)
    parameters = describe_parameters(model)
    if not parameters["adapter_only"]:
        raise RuntimeError(f"adapter not attached: {parameters}")

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=config.training.per_device_train_batch_size,
        per_device_eval_batch_size=config.training.per_device_eval_batch_size,
        gradient_accumulation_steps=config.training.gradient_accumulation_steps,
        num_train_epochs=config.training.num_train_epochs,
        learning_rate=config.training.learning_rate,
        warmup_ratio=config.training.warmup_ratio,
        gradient_checkpointing=config.training.gradient_checkpointing,
        seed=config.training.seed,
        eval_strategy="steps",
        eval_steps=config.training.eval_steps,
        save_strategy="steps",
        save_steps=config.training.save_steps,
        save_total_limit=config.training.save_total_limit,
        logging_steps=1,
        fp16=config.quantization.compute_dtype == "float16",
        report_to=[],
    )

    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=_Dataset(train),
        eval_dataset=_Dataset(evaluation),
        data_collator=_collator(pad_token_id),
        callbacks=[_abort_on_non_finite_loss()],
    )
    result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    elapsed = time.perf_counter() - started

    adapter_dir = output_dir / "adapter"
    trainer.save_model(str(adapter_dir))
    adapter_bytes = sum(f.stat().st_size for f in adapter_dir.rglob("*") if f.is_file())
    tokens = sum(len(example.input_ids) for example in train) * config.training.num_train_epochs

    resumed = args.resume_from_checkpoint is not None
    report = {
        "train_examples": len(train),
        "eval_examples": len(evaluation),
        "train_loss": result.training_loss,
        "runtime_s": round(elapsed, 2),
        # A resumed run replays no steps, so tokens/elapsed would overstate
        # throughput by the fraction already completed.
        "resumed": resumed,
        "tokens_per_s": None if resumed else round(tokens / elapsed, 1),
        "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        "adapter_mib": round(adapter_bytes / 1024**2, 2),
        "learning_rate": config.training.learning_rate,
        "epochs": config.training.num_train_epochs,
        "provenance": provenance,
        "parameters": parameters,
        "eval": {k: v for k, v in trainer.evaluate().items() if isinstance(v, (int, float))},
    }
    (output_dir / "train_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="configs/qlora.yaml")
    parser.add_argument("--model", default=None, help="local weights path")
    parser.add_argument("--train-file", default=None)
    parser.add_argument("--eval-file", default=None)
    parser.add_argument("--max-train-samples", type=int, default=None)
    parser.add_argument("--max-eval-samples", type=int, default=None)
    parser.add_argument(
        "--manifest",
        default="data/manifests/split_v2.json",
        help="data manifest recorded in the run provenance",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--resume-from-checkpoint",
        default=None,
        help="continue from a saved checkpoint directory",
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()
    print(json.dumps(run(args, load_config(args.config)), indent=2))


if __name__ == "__main__":
    main()
