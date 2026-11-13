"""EQ Persistence — save/load EQ state across sessions.

Stores emotional baseline, topic preferences, and style preferences.
"""
from __future__ import annotations

import json
import os
import sqlite3

from learning.eq.baseline import BaselineLearner
from learning.eq.user_state import UserState


def save_eq_state(db_path: str, baseline: BaselineLearner, user_state: UserState) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eq_state (
                id INTEGER PRIMARY KEY,
                emotional_baseline REAL,
                topic_counts TEXT,
                style_counts TEXT,
                user_state TEXT,
                timestamp REAL
            )
        """)
        # One row, replaced on every save (Stage 1.7, #37): it used to append a row per chat
        # turn while only the newest was ever read. The interaction history is saved too, so
        # the baseline isn't recomputed from a single turn after a restart.
        conn.execute("DELETE FROM eq_state WHERE id != 1")
        conn.execute(
            "INSERT OR REPLACE INTO eq_state (id, emotional_baseline, topic_counts, style_counts, user_state, timestamp) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (
                baseline.get_baseline(),
                json.dumps(baseline.topic_counts),
                json.dumps({**baseline.style_counts, "__history__": list(baseline.interaction_history)}),
                json.dumps(user_state.to_dict()),
                __import__("time").time(),
            ),
        )


def load_eq_state(db_path: str) -> tuple[BaselineLearner, UserState] | None:
    if not os.path.exists(db_path):
        return None
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT emotional_baseline, topic_counts, style_counts, user_state FROM eq_state ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        return None
    if row is None:
        return None
    baseline = BaselineLearner()
    baseline.emotional_baseline = row[0]
    baseline.topic_counts = json.loads(row[1])
    style_counts = json.loads(row[2])
    for entry in style_counts.pop("__history__", []):
        baseline.interaction_history.append(entry)
    baseline.style_counts = style_counts
    user_state = UserState.from_dict(json.loads(row[3]))
    return baseline, user_state
