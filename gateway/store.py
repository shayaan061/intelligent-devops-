"""Incident store (§5, Phase 6): every message the gateway broadcasts.

Raw alerts, incident updates, ResponsePlans and responder action records
go into one SQLite table, so an incident's full timeline (detected ->
analyzed -> acted -> verified) survives restarts and can be scored against
experiments/ground_truth.csv.

It is a record, not state: after a restart the gateway starts with no open
incidents, and alerts that are still firing open new ones.

A failing store is logged and ignored; it must never stop the pipeline.
Default journal mode on purpose: WAL needs shared memory, which is
unreliable on Docker Desktop bind mounts.
"""

import json
import logging
import sqlite3

log = logging.getLogger("gateway.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    channel     TEXT NOT NULL,
    type        TEXT,
    incident_id TEXT,
    status      TEXT,
    body        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_incident ON messages (incident_id);
"""


class Store:
    def __init__(self, path):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    def add(self, channel, msg, at):
        try:
            self.db.execute(
                "INSERT INTO messages (at, channel, type, incident_id, status, body) VALUES (?, ?, ?, ?, ?, ?)",
                (at, channel, msg.get("type"), msg.get("incident_id"), msg.get("status"), json.dumps(msg)))
            self.db.commit()
        except Exception as e:
            log.warning("store write failed: %s", e)

    def timeline(self, incident_id):
        rows = self.db.execute("SELECT channel, body FROM messages WHERE incident_id = ? ORDER BY id",
                               (incident_id,)).fetchall()
        return [{"channel": ch, **json.loads(body)} for ch, body in rows]

    def incidents(self, limit=50):
        """Newest first: id, first/last message time, last incident status."""
        rows = self.db.execute(
            """SELECT incident_id, MIN(at), MAX(at),
                      (SELECT status FROM messages m2 WHERE m2.incident_id = m.incident_id
                         AND m2.type = 'incident' ORDER BY id DESC LIMIT 1)
               FROM messages m WHERE incident_id IS NOT NULL
               GROUP BY incident_id ORDER BY MIN(id) DESC LIMIT ?""", (limit,)).fetchall()
        return [{"incident_id": i, "first_at": a, "last_at": b, "status": s} for i, a, b, s in rows]
