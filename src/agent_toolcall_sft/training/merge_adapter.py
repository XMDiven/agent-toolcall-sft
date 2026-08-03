"""Fold a trained LoRA adapter into the base weights for deployment.

The frozen evaluation loaded the base model in fp16 and attached the adapter
on top -- 4-bit quantisation was a training-time memory measure only. Merging
therefore reproduces the evaluated model rather than approximating it, and the
result runs anywhere fp16 runs, without PEFT and without the per-layer low-rank
matmuls that cost roughly 60% of the serving latency.

Numerical equality still has to be demonstrated on the target hardware, not
assumed: see `docs/evidence/deployment_parity.md`.
"""

import argparse
import json
from pathlib import Path

from agent_toolcall_sft.evaluation.evidence import adapter_metadata, sha256_file


def merge(base_model: str, adapter: str, output_dir: Path) -> dict:
    """Write base+adapter merged into a standalone fp16 model."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if output_dir.exists():
        raise ValueError(f"refusing to overwrite {output_dir}")

    # fp16 on CPU: identical arithmetic to the evaluated load, and merging does
    # not need the GPU.
    model = AutoModelForCausalLM.from_pretrained(base_model, dtype=torch.float16)
    model = PeftModel.from_pretrained(model, adapter)
    model = model.merge_and_unload()

    output_dir.mkdir(parents=True)
    model.save_pretrained(output_dir)
    AutoTokenizer.from_pretrained(base_model).save_pretrained(output_dir)

    return {
        "base_model": base_model,
        "adapter": adapter_metadata(adapter),
        "output_dir": str(output_dir),
        "files": {
            path.name: sha256_file(path)
            for path in sorted(output_dir.iterdir())
            if path.is_file()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    record = merge(args.base_model, args.adapter, args.out)
    (args.out / "merge_provenance.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in record.items() if k != "files"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
