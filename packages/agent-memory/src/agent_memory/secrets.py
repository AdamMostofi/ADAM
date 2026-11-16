"""Find and redact secrets before anything is written (design section 11).

Every payload and every summary field is scanned before it reaches the log or
the archive. Each match is replaced with `[SECRET:<rule>:<fingerprint>]` and
described by a redaction record: the rule, where it was, and a keyed
fingerprint. The value itself is never stored.

Rules follow common Gitleaks patterns, plus an entropy check for assignments
of random-looking values to secret-sounding names. Detection is best effort:
a secret in a format no rule knows can still get through, so `amem purge`
exists for the leaks that are found later.

**Speed (Stage 3.1).** Hooks scan every file the agent touches, so the scan
avoids work without changing what it finds:
- a rule's regex runs only when its fixed prefix appears at all (a C-level
  substring check);
- assignments are found from the secret-sounding keyword outward, instead of
  trying a name at every word boundary;
- results are cached per content, so computing a content id and storing the
  same content scan once.

Measured on the ADAM repository's files: one scan of each of its files went from 6.0 s to 0.4 s.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import re
from collections import OrderedDict
from dataclasses import dataclass

# (rule name, bytes pattern, group holding the secret value)
RULES: list[tuple[str, re.Pattern, int]] = [
    ("private-key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), 0),
    ("aws-access-key", re.compile(rb"\b((?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16})\b"), 1),
    ("github-token", re.compile(rb"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,})\b"), 1),
    ("github-fine-grained-token", re.compile(rb"\b(github_pat_[A-Za-z0-9_]{60,})\b"), 1),
    ("anthropic-api-key", re.compile(rb"\b(sk-ant-[A-Za-z0-9_\-]{20,})"), 1),
    ("openai-api-key", re.compile(rb"\b(sk-(?:proj-)?[A-Za-z0-9_\-]{32,})"), 1),
    ("slack-token", re.compile(rb"\b(xox[abposr]-[A-Za-z0-9-]{10,})\b"), 1),
    ("google-api-key", re.compile(rb"\b(AIza[0-9A-Za-z_\-]{35})\b"), 1),
    ("gitlab-token", re.compile(rb"\b(glpat-[A-Za-z0-9_\-]{20,})"), 1),
    ("npm-token", re.compile(rb"\b(npm_[A-Za-z0-9]{36})\b"), 1),
    ("huggingface-token", re.compile(rb"\b(hf_[A-Za-z0-9]{30,})\b"), 1),
    ("bearer-token", re.compile(rb"(?i)\bbearer\s+([A-Za-z0-9_\-.=+/]{20,})"), 1),
    ("stripe-key", re.compile(rb"\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,})\b"), 1),
    ("jwt", re.compile(rb"\b(eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})\b"), 1),
    # Anchored at "://" (a scheme prefix tried at every letter made this rule 94% of all scanning time).
    ("url-credentials", re.compile(rb"://[^\s:/@]+:([^\s@/]{3,})@"), 1),
]

# A rule's regex only runs when one of these fixed strings is in the content (lower-cased ones: case-insensitive).
NEEDLES: dict[str, tuple[bytes, ...]] = {
    "private-key": (b"PRIVATE KEY",), "aws-access-key": (b"AKIA", b"ASIA", b"ABIA", b"ACCA"),
    "github-token": (b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_"), "github-fine-grained-token": (b"github_pat_",),
    "anthropic-api-key": (b"sk-ant-",), "openai-api-key": (b"sk-",), "slack-token": (b"xox",),
    "google-api-key": (b"AIza",), "gitlab-token": (b"glpat-",), "npm-token": (b"npm_",), "huggingface-token": (b"hf_",),
    "stripe-key": (b"_live_", b"_test_"), "jwt": (b"eyJ",), "url-credentials": (b"://",),
}
LOWER_NEEDLES = {"bearer-token": (b"bearer",)}

# NAME = value, NAME: value, NAME="value" where NAME sounds secret. Found from the keyword outward.
KEYWORD = re.compile(rb"(?i)password|passwd|secret|token|api[_\-]?key|access[_\-]?key|private[_\-]?key|"
                     rb"client[_\-]?secret|auth")
NAME_CHAR = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
ASSIGN_TAIL = re.compile(rb"[\"']?\s*[:=]\s*[\"']?([^\s\"'`,;]{8,})")
CACHE_MIN = 2048   # cache scans of contents at least this big (smaller ones are cheaper to rescan)
ENTROPY_THRESHOLD = 3.0          # bits per character
PLACEHOLDERS = re.compile(rb"(?i)^(\$\{?[A-Za-z_]+\}?|<[^>]+>|x+|\*+|changeme|example|placeholder|your[_\-]?\w*|"
                          rb"none|null|true|false|redacted|\[secret:.*)$")
# Code that reads a secret rather than containing one: os.environ['X'], getenv("X"), settings.API_KEY.
CODE_REFERENCE = re.compile(rb"[\[\]\(\)<>{}]|\|\||&&"
                            rb"|^(?:os\.|process\.env|env\.|getenv|settings\.|config\.|self\.|this\.|args\.)"
                            rb"|^[A-Za-z_]+$"   # a bare identifier ("max_tokens") is a name, not a secret
                            # an attribute path in code ("item.tokens", "cfg.auth.api_key"), not a secret
                            rb"|^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+,?$")


@dataclass(frozen=True)
class Redaction:
    field: str          # "payload" or "summary:<name>"
    rule: str
    start: int          # byte offsets in the original content
    end: int
    fingerprint: str    # keyed hash of the value: compares leaks without revealing them

    def record(self) -> dict:
        return {"field": self.field, "rule": self.rule, "start": self.start, "end": self.end,
                "fingerprint": self.fingerprint}


def entropy(value: bytes) -> float:
    if not value:
        return 0.0
    counts = {}
    for b in value:
        counts[b] = counts.get(b, 0) + 1
    return -sum(c / len(value) * math.log2(c / len(value)) for c in counts.values())


class SecretScanner:
    def __init__(self, fingerprint_key: bytes, denylist: set[str] | None = None):
        self._key = fingerprint_key
        # Fingerprints of known leaked values (purge, Stage 2.7): redacted wherever they appear.
        self.denylist = set(denylist or ())
        self._cache: OrderedDict = OrderedDict()

    def fingerprint(self, value: bytes) -> str:
        return hmac.new(self._key, value, hashlib.sha256).hexdigest()[:16]

    def _matches(self, data: bytes) -> list[tuple[int, int, str]]:
        found: list[tuple[int, int, str]] = []
        lower = data.lower()
        for name, pattern, group in RULES:
            needles = NEEDLES.get(name)
            if needles is not None and not any(n in data for n in needles):
                continue
            low = LOWER_NEEDLES.get(name)
            if low is not None and not any(n in lower for n in low):
                continue
            for m in pattern.finditer(data):
                found.append((m.start(group), m.end(group), name))
        seen_names: set[int] = set()
        for k in KEYWORD.finditer(data):
            start = k.start()
            while start > 0 and data[start - 1] in NAME_CHAR:
                start -= 1
            if start in seen_names or (start > 0 and data[start - 1] in NAME_CHAR):
                continue
            seen_names.add(start)
            end = k.end()
            while end < len(data) and data[end] in NAME_CHAR:
                end += 1
            m = ASSIGN_TAIL.match(data, end)
            if m is None:
                continue
            value = m.group(1)
            if data[max(0, start - 1):start] == b"[" and data[start:end].upper() == b"SECRET":
                continue   # one of our own redaction markers
            if PLACEHOLDERS.match(value) or CODE_REFERENCE.search(value) or entropy(value) < ENTROPY_THRESHOLD:
                continue
            found.append((m.start(1), m.end(1), "generic-secret-assignment"))
        # Keep the earliest, then longest, non-overlapping matches.
        found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
        chosen, end = [], -1
        for start, stop, name in found:
            if start >= end:
                chosen.append((start, stop, name))
                end = stop
        return chosen

    def redact(self, data: bytes, field: str) -> tuple[bytes, list[Redaction]]:
        """Return the content with every secret replaced, and a record of each replacement."""
        key = None
        if len(data) >= CACHE_MIN:
            key = (field, len(self.denylist), hashlib.blake2b(data, digest_size=20).digest())
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        result = self._redact(data, field)
        if key is not None:
            self._cache[key] = result
            if len(self._cache) > 64:
                self._cache.popitem(last=False)
        return result

    def _redact(self, data: bytes, field: str) -> tuple[bytes, list[Redaction]]:
        matches = self._matches(data)
        out, redactions, last = [], [], 0
        for start, stop, rule in matches:
            value = data[start:stop]
            fp = self.fingerprint(value)
            out.append(data[last:start])
            out.append(f"[SECRET:{rule}:{fp}]".encode())
            redactions.append(Redaction(field, rule, start, stop, fp))
            last = stop
        out.append(data[last:])
        result = b"".join(out)
        if self.denylist:
            result, extra = self._redact_denylisted(result, field)
            redactions.extend(extra)
        return result, redactions

    def _redact_denylisted(self, data: bytes, field: str) -> tuple[bytes, list[Redaction]]:
        # Purged values are known only by fingerprint, so candidate tokens are fingerprinted and compared.
        redactions = []
        for m in re.finditer(rb"[^\s\"'`,;:=()\[\]{}<>]{8,}", data):
            fp = self.fingerprint(m.group(0))
            if fp in self.denylist:
                redactions.append(Redaction(field, "denylisted", m.start(), m.end(), fp))
        for r in sorted(redactions, key=lambda r: r.start, reverse=True):
            data = data[:r.start] + f"[SECRET:denylisted:{r.fingerprint}]".encode() + data[r.end:]
        return data, redactions
