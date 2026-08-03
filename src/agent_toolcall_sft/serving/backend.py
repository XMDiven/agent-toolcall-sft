"""Model backends for the router service.

Generation is isolated behind this interface so the API's validation — the part
that decides what reaches a caller — is testable without a GPU. Everything that
can reject an output lives outside the backend.
"""

from typing import Protocol

from agent_toolcall_sft.data.records import DatasetRecord


class RouterBackend(Protocol):
    """Produce one raw completion for one routing request."""

    def generate(self, record: DatasetRecord) -> str: ...


class FakeBackend:
    """Return a fixed string, so tests can drive every validation path."""

    def __init__(self, output: str):
        self._output = output

    def generate(self, record: DatasetRecord) -> str:
        return self._output


class LocalBackend:
    """Load a merged fp16 model on this machine and decode greedily.

    Prompt rendering and decoding come from the evaluation modules rather than
    being restated here: an API that prompts differently than the frozen run is
    no longer described by the frozen run's numbers.
    """

    def __init__(self, model_path: str, device: str = "mps"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._device = device
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModelForCausalLM.from_pretrained(model_path, dtype=torch.float16)
        self._model.to(device)
        self._model.eval()

    def generate(self, record: DatasetRecord) -> str:
        import torch

        from agent_toolcall_sft.evaluation.prompt import render_messages
        from agent_toolcall_sft.evaluation.runner import DECODING

        prompt = self._tokenizer.apply_chat_template(
            render_messages(record),
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=DECODING.enable_thinking,
        )
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._device)

        with torch.inference_mode():
            output = self._model.generate(
                **inputs,
                max_new_tokens=DECODING.max_new_tokens,
                do_sample=DECODING.do_sample,
                num_beams=DECODING.num_beams,
                pad_token_id=self._tokenizer.pad_token_id or self._tokenizer.eos_token_id,
            )

        completion = output[0][inputs["input_ids"].shape[-1]:]

        return self._tokenizer.decode(completion, skip_special_tokens=True).strip()
