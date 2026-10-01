"""SQLite persistence. All timestamps are UTC epoch seconds (spec §6.4)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .energy import CounterReading
from .events import Event
from .sessions import Session
from .snapshot import Snapshot, snapshot_from_dict, snapshot_to_dict

SCHEMA_VERSION = 1
COUNTER_MIN_INTERVAL_S = 600
EVENTS_RETENTION_DAYS = 90
DAY_S = 86400

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY, ts REAL NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS counters (id INTEGER PRIMARY KEY, ts REAL NOT NULL,
    in_wh REAL NOT NULL, out_wh REAL NOT NULL);
CREATE INDEX IF NOT EXISTS counters_ts ON counters(ts);
CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
    start_ts REAL NOT NULL, end_ts REAL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_start ON sessions(start_ts);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL,
    rule_id TEXT NOT NULL, priority TEXT NOT NULL, title_key TEXT NOT NULL, body_key TEXT NOT NULL,
    params TEXT NOT NULL, desktop TEXT NOT NULL, telegram TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class Storage:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()
        self.set_meta("schema_version", str(SCHEMA_VERSION))

    def close(self) -> None:
        self.conn.close()

    # samples
    def add_sample(self, s: Snapshot) -> None:
        self.conn.execute("INSERT INTO samples(ts, data) VALUES (?, ?)", (s.ts, json.dumps(snapshot_to_dict(s))))
        self.conn.commit()

    def samples_since(self, ts: float) -> list[Snapshot]:
        rows = self.conn.execute("SELECT data FROM samples WHERE ts >= ? ORDER BY ts", (ts,))
        return [snapshot_from_dict(json.loads(row["data"])) for row in rows]

    # counters
    def add_counter(self, ts: float, in_wh: float, out_wh: float, force: bool = False) -> bool:
        last = self.last_counter()
        if not force and last is not None and ts - last.ts < COUNTER_MIN_INTERVAL_S:
            return False
        self.conn.execute("INSERT INTO counters(ts, in_wh, out_wh) VALUES (?, ?, ?)", (ts, in_wh, out_wh))
        self.conn.commit()
        return True

    def counters(self, since: float | None = None) -> list[CounterReading]:
        rows = self.conn.execute("SELECT ts, in_wh, out_wh FROM counters WHERE ts >= ? ORDER BY ts",
                                 (since if since is not None else -1e18,))
        return [CounterReading(row["ts"], row["in_wh"], row["out_wh"]) for row in rows]

    def last_counter(self) -> CounterReading | None:
        row = self.conn.execute("SELECT ts, in_wh, out_wh FROM counters ORDER BY ts DESC LIMIT 1").fetchone()
        return CounterReading(row["ts"], row["in_wh"], row["out_wh"]) if row else None

    # sessions
    def save_session(self, s: Session) -> int:
        data = json.dumps(s.to_dict())
        if s.id is None:
            cur = self.conn.execute("INSERT INTO sessions(kind, start_ts, end_ts, data) VALUES (?, ?, ?, ?)",
                                    (s.kind, s.start_ts, s.end_ts, data))
            s.id = cur.lastrowid
            self.conn.execute("UPDATE sessions SET data = ? WHERE id = ?", (json.dumps(s.to_dict()), s.id))
        else:
            self.conn.execute("UPDATE sessions SET kind = ?, start_ts = ?, end_ts = ?, data = ? WHERE id = ?",
                              (s.kind, s.start_ts, s.end_ts, data, s.id))
        self.conn.commit()
        return s.id

    def sessions(self, since: float | None = None) -> list[Session]:
        rows = self.conn.execute("SELECT id, data FROM sessions WHERE start_ts >= ? ORDER BY start_ts",
                                 (since if since is not None else -1e18,))
        return [self._session(row) for row in rows]

    def open_session(self) -> Session | None:
        row = self.conn.execute(
            "SELECT id, data FROM sessions WHERE end_ts IS NULL ORDER BY start_ts DESC LIMIT 1").fetchone()
        return self._session(row) if row else None

    @staticmethod
    def _session(row: sqlite3.Row) -> Session:
        s = Session.from_dict(json.loads(row["data"]))
        s.id = row["id"]
        return s

    # events
    def add_event(self, e: Event) -> int:
        cur = self.conn.execute(
            "INSERT INTO events(ts, kind, rule_id, priority, title_key, body_key, params, desktop, telegram)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (e.ts, e.kind, e.rule_id, e.priority, e.title_key, e.body_key,
             json.dumps(e.params, ensure_ascii=False), e.desktop, e.telegram))
        self.conn.commit()
        return cur.lastrowid

    def set_delivery(self, event_id: int, channel: str, status: str) -> None:
        if channel not in ("desktop", "telegram"):
            raise ValueError(f"unknown channel {channel!r}")
        self.conn.execute(f"UPDATE events SET {channel} = ? WHERE id = ?", (status, event_id))
        self.conn.commit()

    def events(self, limit: int = 500) -> list[Event]:
        rows = self.conn.execute("SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
        return [
            Event(ts=row["ts"], kind=row["kind"], rule_id=row["rule_id"], priority=row["priority"],
                  title_key=row["title_key"], body_key=row["body_key"], params=json.loads(row["params"]),
                  desktop=row["desktop"], telegram=row["telegram"], id=row["id"])
            for row in rows
        ]

    # maintenance
    def purge(self, now: float, samples_days: int) -> None:
        self.conn.execute("DELETE FROM samples WHERE ts < ?", (now - samples_days * DAY_S,))
        self.conn.execute("DELETE FROM events WHERE ts < ?", (now - EVENTS_RETENTION_DAYS * DAY_S,))
        self.conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                          (key, value))
        self.conn.commit()
