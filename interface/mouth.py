"""Mouth — TinyChat15M served by llama-server (OpenAI-compatible HTTP API)."""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_MODEL = os.path.normpath(os.path.join(_HERE, "..", "models", "TinyChat15M.gguf"))
SYSTEM_PROMPT = "You are ADAM. Answer briefly and truthfully. If unsure, say so."

# chisel: 15M model clamps to 128 tokens; swap to a larger model when coherence matters.
_CONTEXT_CHARS = 60

_SMALL_TALK = {
    "hello": "Hello. I am ADAM. What shall we work on?",
    "hi": "Hello. I am ADAM. What shall we work on?",
    "hey": "Hello. I am ADAM. What shall we work on?",
    "yo": "Hello. I am ADAM. What shall we work on?",
    "good morning": "Good morning. What shall we work on?",
    "good evening": "Good evening. What shall we work on?",
    "who are you": "I am ADAM, a local machine intelligence with a persistent memory.",
    "what are you": "I am ADAM, a local machine intelligence with a persistent memory.",
    "what is your name": "My name is ADAM.",
    "thanks": "You are welcome.",
    "thank you": "You are welcome.",
    "bye": "Goodbye.",
    "goodbye": "Goodbye.",
}

_DEFAULT_SERVER_CANDIDATES = [
    "/home/adam/llama.cpp/build/bin/llama-server",
    "llama-server",
]


class Mouth:
    def __init__(
        self,
        model_path: str | None = None,
        host: str = "127.0.0.1",
        port: int | None = None,
        server_bin: str | None = None,
        auto_start: bool = True,
    ):
        self.model_path = model_path or os.environ.get("ADAM_MOUTH_MODEL", _DEFAULT_MODEL)
        self.host = os.environ.get("ADAM_MOUTH_HOST", host)
        self.port = int(os.environ.get("ADAM_MOUTH_PORT", port or 8080))
        self.server_bin = server_bin or os.environ.get("ADAM_LLAMA_SERVER", self._find_server())
        self.auto_start = auto_start
        self._proc: subprocess.Popen | None = None
        if auto_start:
            atexit.register(self.close)

    def _find_server(self) -> str:
        for candidate in _DEFAULT_SERVER_CANDIDATES:
            if candidate == "llama-server" or os.path.exists(candidate):
                return candidate
        return "llama-server"

    @property
    def _base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def is_running(self) -> bool:
        try:
            with urllib.request.urlopen(self._base_url + "/health", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def _ensure_server(self) -> None:
        if self.is_running():
            return
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Mouth model not found: {self.model_path}")
        if self.server_bin != "llama-server" and not os.path.exists(self.server_bin):
            raise FileNotFoundError(f"llama-server binary not found: {self.server_bin}")
        self._proc = subprocess.Popen(
            [self.server_bin, "-m", self.model_path, "-c", "512", "--host", self.host, "--port", str(self.port)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        for _ in range(60):
            time.sleep(1)
            if self.is_running():
                return
        raise RuntimeError("llama-server did not become ready in time")

    def speak(self, prompt: str, max_tokens: int = 48, stop: list[str] | None = None) -> str:
        if self.auto_start:
            self._ensure_server()
        payload = json.dumps(
            {
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": 0.4,
                "top_p": 0.9,
                "stop": stop or ["<|im_end|>", "<|im_start|>", "\nUser:", "\nuser:"],
            }
        ).encode()
        request = urllib.request.Request(
            self._base_url + "/v1/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read())
        return _clean(data["choices"][0]["text"])

    def format_response(self, user_message: str, params: dict, context: str = "") -> str:
        reply = _small_talk(user_message)
        if reply is not None:
            return reply
        try:
            text = self.speak(self._build_prompt(user_message, params, context), max_tokens=24)
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
            # chisel: retry only the 128-token limit; add server-side token counting if prompts grow.
            text = self.speak(self._build_prompt(user_message[:40], params), max_tokens=24)
        return text or "I do not have a good answer for that yet."

    @staticmethod
    def _build_prompt(user_message: str, params: dict, context: str = "") -> str:
        warmth = params.get("warmth", "medium")
        depth = params.get("depth", "detailed")
        tone = params.get("tone", "neutral")
        system = (
            f"{SYSTEM_PROMPT}\n"
            f"Tone: {warmth} warmth, {depth} depth, {tone} affect."
        )
        context = context.strip()[:_CONTEXT_CHARS]
        if context:
            system += f"\nContext: {context}"
        return (
            f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user_message}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=5)


def _clean(text: str) -> str:
    for marker in ("<|im_end|>", "<|im_start|>", "\nUser:", "\nuser:", "[/INST]"):
        text = text.split(marker)[0]
    return text.strip().lstrip(",'’\"` -")


def _small_talk(message: str) -> str | None:
    key = " ".join(message.lower().strip().rstrip("!.,? ").split())
    return _SMALL_TALK.get(key)
