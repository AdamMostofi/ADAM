"""The canonical event format (design section 4).

Every adapter translates its agent's events into this one versioned format,
so memory looks the same whichever agent produced it. A stored record also
gets its place in the log and its hash chain from the store.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

KINDS = frozenset({
    "session_start", "user_message", "assistant_message", "tool_call", "tool_result",
    "file_change", "verification", "decision", "goal", "task", "note", "compaction",
    "session_end", "subagent_start", "subagent_stop", "capture_gap", "import",
    # Stage 2.2: content withheld because its path is explicitly excluded (design 5.3).
    "exclusion",
    # Stage 2.3: declared structure (design 6): development paths, blockers, typed relations, retractions.
    "path", "blocker", "relation", "retraction",
    # Stage 2.5: conflicting concurrent changes, grouped git operations, and recoveries (design 8).
    "conflict", "change_group", "recovery",
    # Stage 2.8: knowledge entries (requirements, bugs, solutions ...) and topics (architecture revision 3, 4.3).
    "entry", "topic",
})

COMPLETENESS = ("captured", "partial", "unavailable", "imported")


class SchemaError(ValueError):
    """An event doesn't fit the canonical format."""


@dataclass
class EventInput:
    """What an adapter hands to the store. The store adds ids, order, hashes and redactions."""

    kind: str
    session_id: str
    writer_id: str
    payload: bytes | str | None = None
    summary_fields: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    agent: str = "unknown"
    agent_version: str = ""
    adapter_version: str = ""
    occurred_at: str | None = None          # ISO 8601; the store fills recorded_at
    completeness: str = "captured"
    idempotency_key: str | None = None
    path: str | None = None                 # for file content: checked against exclusions

    def validate(self) -> None:
        if self.kind not in KINDS:
            raise SchemaError(f"unknown kind {self.kind!r}; expected one of {sorted(KINDS)}")
        if self.completeness not in COMPLETENESS:
            raise SchemaError(f"unknown completeness {self.completeness!r}; expected one of {COMPLETENESS}")
        if not self.session_id or not self.writer_id:
            raise SchemaError("session_id and writer_id are required")
        try:
            canonical_json(self.summary_fields)
        except (TypeError, ValueError) as err:
            raise SchemaError(f"summary_fields must be JSON-serializable: {err}") from err


@dataclass(frozen=True)
class Event:
    """A stored event: the canonical record, as read back from the log."""

    log_position: int
    event_id: str
    schema_version: int
    kind: str
    session_id: str
    parent_id: str | None
    writer_id: str
    writer_seq: int
    agent: str
    agent_version: str
    adapter_version: str
    occurred_at: str
    recorded_at: str
    payload_object: str | None
    summary_fields: dict[str, Any]
    completeness: str
    redactions: list[dict]
    idempotency_key: str | None
    prev_hash: str
    record_hash: str

    def hashed_fields(self) -> dict:
        """Everything the record hash covers: all fields except log_position and the hash itself.

        log_position is assigned by the global order and is checked separately;
        the chain is per writer.
        """
        return {
            "event_id": self.event_id, "schema_version": self.schema_version, "kind": self.kind,
            "session_id": self.session_id, "parent_id": self.parent_id, "writer_id": self.writer_id,
            "writer_seq": self.writer_seq, "agent": self.agent, "agent_version": self.agent_version,
            "adapter_version": self.adapter_version, "occurred_at": self.occurred_at,
            "recorded_at": self.recorded_at, "payload_object": self.payload_object,
            "summary_fields": self.summary_fields, "completeness": self.completeness,
            "redactions": self.redactions, "idempotency_key": self.idempotency_key,
            "prev_hash": self.prev_hash,
        }


def canonical_json(value: Any) -> str:
    """One byte-stable JSON encoding, used for hashing and storage."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
