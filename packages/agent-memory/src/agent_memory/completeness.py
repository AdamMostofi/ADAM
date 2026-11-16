"""What `amem verify` proves, and what it can't (#93).

`verify` checks **archive integrity**: the hash chains, objects, references,
checkpoints, structure and the derived layer. That proves the records that
were captured are intact and continuous. It cannot prove that something the
hooks never saw didn't happen.

So a verify report also gives three things integrity can't cover, each from
evidence the engine keeps:
- **capture**: completeness within the instrumentation. Sessions that ended
  cleanly versus ones that never recorded an end, events by completeness,
  and whether the last reconciliation succeeded. Reconciliation is what
  catches file changes the hooks missed.
- **known gaps**: `capture_gap` records (something was missed, and the
  record names what) and `partial` records (part of something was captured,
  and the record says what's missing).
- **attribution**: file changes recorded as `unattributed`, whose author
  (the agent, the user, git) couldn't be told apart (#81).

The exit code of `amem verify` stays tied to integrity alone. A gap is
honest information, not corruption.
"""
from __future__ import annotations

import json

EXAMPLES = 20


def capture_report(store) -> dict:
    conn = store._connect()
    try:
        by_completeness = dict(conn.execute("SELECT completeness, COUNT(*) FROM events GROUP BY completeness"))
        started = {r[0] for r in conn.execute("SELECT DISTINCT session_id FROM events WHERE kind = 'session_start'")}
        ended = {r[0] for r in conn.execute("SELECT DISTINCT session_id FROM events WHERE kind = 'session_end'")}
        gaps = conn.execute("SELECT event_id, session_id, summary_fields FROM events WHERE kind = 'capture_gap' "
                            "ORDER BY log_position DESC").fetchall()
        partial = conn.execute("SELECT event_id, session_id, kind, summary_fields FROM events WHERE completeness = "
                               "'partial' ORDER BY log_position DESC").fetchall()
        attribution = dict(conn.execute(
            "SELECT json_extract(summary_fields, '$.attribution'), COUNT(*) FROM events WHERE kind = 'file_change' "
            "AND json_extract(summary_fields, '$.attribution') IS NOT NULL GROUP BY 1"))
        unattributed = conn.execute(
            "SELECT event_id, session_id, json_extract(summary_fields, '$.path') FROM events WHERE kind = "
            "'file_change' AND json_extract(summary_fields, '$.attribution') = 'unattributed' "
            "ORDER BY log_position DESC LIMIT ?", (EXAMPLES,)).fetchall()
        reconcile = None
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'reconcile_meta'").fetchone():
            meta = dict(conn.execute("SELECT key, value FROM reconcile_meta WHERE key IN ('ok', 'error')"))
            if "ok" in meta:
                reconcile = {"ok": json.loads(meta["ok"]),
                             "error": json.loads(meta["error"]) if not json.loads(meta["ok"]) and "error" in meta
                             else None}
    finally:
        conn.close()

    def fields(raw):
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    not_ended = sorted(started - ended)
    return {
        "capture": {
            "scope": "within the instrumentation: what the agent's hooks and the reconciler can observe",
            "sessions": len(started), "ended_cleanly": len(started & ended), "not_ended": len(not_ended),
            "not_ended_sessions": not_ended[:EXAMPLES], "events_by_completeness": by_completeness,
            "last_reconcile": reconcile,
        },
        "known_gaps": {
            "capture_gaps": len(gaps), "partial": len(partial),
            "examples": [{"event": e, "session": s, "missed": fields(f).get("missed_kind"),
                          "reason": fields(f).get("reason")} for e, s, f in gaps[:EXAMPLES]] +
                        [{"event": e, "session": s, "kind": k, "missing": fields(f).get("missing")}
                         for e, s, k, f in partial[:EXAMPLES]],
        },
        "attribution": {
            "by_attribution": attribution, "unattributed": attribution.get("unattributed", 0),
            "examples": [{"event": e, "session": s, "path": p} for e, s, p in unattributed],
        },
    }


def statement(report: dict) -> list[str]:
    """The four results in plain words, for people."""
    integrity = report.get("ok")
    cap, gaps, attr = report["capture"], report["known_gaps"], report["attribution"]
    lines = [
        "archive integrity: " + ("verified: the captured records are intact and continuous" if integrity else
                                 f"FAILED: {len(report.get('problems', []))} problem(s)"),
        f"capture (within the instrumentation): {cap['sessions']} session(s), {cap['ended_cleanly']} ended "
        f"cleanly, {cap['not_ended']} never recorded an end"
        + ("" if cap["last_reconcile"] is None else
           "; last reconciliation " + ("succeeded" if cap["last_reconcile"]["ok"] else "FAILED")),
        f"known gaps: {gaps['capture_gaps']} capture gap(s), {gaps['partial']} partial record(s)",
        f"uncertain attribution: {attr['unattributed']} file change(s) unattributed",
    ]
    return lines
