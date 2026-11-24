"""L: the leaderboard/results store (WS3.4).

L is pinned to Cloud X, so the store is a SQLite file on X.  Y submits a score
when a match ends and asks for the top rows when End Z's U view opens.  Kept
free of sockets/pygame so it can be unit-tested in memory.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

MAX_NAME = 24
TOP_LIMIT = 50
DEFAULT_TOP = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    score INTEGER NOT NULL,
    deaths INTEGER NOT NULL DEFAULT 0,
    workload TEXT NOT NULL DEFAULT '',
    seed INTEGER,
    placement TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created REAL NOT NULL
)
"""


class LeaderboardError(ValueError):
    """Invalid submission; the message is meant for the panel/log."""


class Leaderboard:
    """A small append-only score table, ordered by score then submission time."""

    def __init__(self, path=":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        self.db.commit()

    def submit(self, entry):
        """Insert one result; returns ``{"id", "rank", "rows"}``."""
        if not isinstance(entry, dict):
            raise LeaderboardError("entry must be an object")
        name = str(entry.get("name") or "player").strip()[:MAX_NAME] or "player"
        try:
            score = int(entry.get("score", 0))
            deaths = int(entry.get("deaths", 0))
        except (TypeError, ValueError):
            raise LeaderboardError("score and deaths must be integers") from None
        if score < 0 or deaths < 0:
            raise LeaderboardError("score and deaths must be >= 0")
        try:
            seed = int(entry["seed"]) if entry.get("seed") is not None else None
        except (TypeError, ValueError):
            seed = None
        cursor = self.db.execute(
            "INSERT INTO scores (name, score, deaths, workload, seed, placement,"
            " source, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, score, deaths, str(entry.get("workload") or ""), seed,
             str(entry.get("placement") or ""),
             str(entry.get("source") or "manual"), time.time()))
        self.db.commit()
        entry_id = int(cursor.lastrowid)
        return {"entry_id": entry_id, "rank": self._rank(score, entry_id),
                "rows": self.top(DEFAULT_TOP)}

    def _rank(self, score, entry_id):
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM scores"
            " WHERE score > ? OR (score = ? AND id < ?)",
            (score, score, entry_id)).fetchone()
        return int(row["n"]) + 1

    def top(self, limit=DEFAULT_TOP):
        try:
            limit = max(1, min(TOP_LIMIT, int(limit)))
        except (TypeError, ValueError):
            limit = DEFAULT_TOP
        rows = self.db.execute(
            "SELECT id, name, score, deaths, workload, placement, source, created"
            " FROM scores ORDER BY score DESC, created ASC, id ASC LIMIT ?",
            (limit,)).fetchall()
        return [dict(row) for row in rows]

    def count(self):
        return int(self.db.execute("SELECT COUNT(*) AS n FROM scores").fetchone()["n"])

    def reset(self):
        """Drop every row (tests and a deliberate demo reset)."""
        self.db.execute("DELETE FROM scores")
        self.db.commit()

    def close(self):
        self.db.close()
