"""Mouth — TinyChat15M wrapper for persona-formatted response generation."""
from __future__ import annotations

from typing import Any
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class Mouth:
    def __init__(self, model_name: str = "sshleifer/tiny-gpt2"):
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model: Any = AutoModelForCausalLM.from_pretrained(model_name)
        self._model.eval()

    def speak(self, prompt: str, max_tokens: int = 100) -> str:
        inputs = self._tokenizer(prompt, return_tensors="pt")
        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
            )
        return self._tokenizer.decode(outputs[0], skip_special_tokens=True).strip()

    def format_response(self, core_response: str, params: dict) -> str:
        prompt = f"[PARAMS] warmth={params.get('warmth', 'medium')}, depth={params.get('depth', 'detailed')}\n[RESPONSE] {core_response}\n[OUTPUT]"
        return self.speak(prompt)
