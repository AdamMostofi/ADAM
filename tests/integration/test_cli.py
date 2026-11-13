"""The CLI answers a single-shot message (Stage 1.8, #44: every README capability has a test)."""
from __future__ import annotations

import sys

import interface.cli as cli


class QuietMouth:
    def format_response(self, message, params, context=""):
        return "hello from the test mouth"


def test_single_shot_message_prints_a_response(monkeypatch, capsys):
    real_core = cli.ADAMCore
    monkeypatch.setattr(cli, "ADAMCore", lambda: real_core(mouth=QuietMouth()))
    monkeypatch.setattr(sys, "argv", ["cli", "what", "is", "a", "fact"])
    cli.main()
    assert "hello from the test mouth" in capsys.readouterr().out
