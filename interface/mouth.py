"""Mouth — TinyChat15M served by llama-server (OpenAI-compatible HTTP API)."""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_MODEL = os.path.normpath(os.path.join(_HERE, "..", "..", "models", "TinyChat15M.gguf"))
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

    def speak(self, prompt: str, max_tokens: int = 100) -> str:
        if self.auto_start:
            self._ensure_server()
        payload = json.dumps(
            {"prompt": prompt, "max_tokens": max_tokens, "temperature": 0.7, "top_p": 0.9}
        ).encode()
        request = urllib.request.Request(
            self._base_url + "/v1/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read())
        return data["choices"][0]["text"].strip()

    def format_response(self, core_response: str, params: dict) -> str:
        return self.speak(self._build_prompt(core_response, params))

    @staticmethod
    def _build_prompt(core_response: str, params: dict) -> str:
        warmth = params.get("warmth", "medium")
        depth = params.get("depth", "detailed")
        return (
            f"[PARAMS] warmth={warmth}, depth={depth}\n"
            f"[RESPONSE] {core_response}\n"
            f"[OUTPUT]"
        )

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=5)
