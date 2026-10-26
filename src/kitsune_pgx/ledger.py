from __future__ import annotations

import sqlite3
import socket
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  srr             TEXT PRIMARY KEY,
  gse             TEXT NOT NULL,
  srp             TEXT NOT NULL DEFAULT '',
  sample_id       TEXT NOT NULL,
  donor_id        TEXT,
  disease         TEXT,
  tier            TEXT,

  state           TEXT NOT NULL DEFAULT 'PENDING',
  claimed_by      TEXT,
  claimed_at      TEXT,
  heartbeat_at    TEXT,
  attempts        INTEGER NOT NULL DEFAULT 0,
  last_error      TEXT,

  chemistry       TEXT,
  cb_len          INTEGER,
  umi_len         INTEGER,
  r1_len          INTEGER,
  r2_len          INTEGER,
  source          TEXT,
  fastq_bytes     INTEGER,
  read_count      INTEGER,

  ref_manifest_sha TEXT,
  gencode_h5ad    TEXT,
  noncode_h5ad    TEXT,
  audit_cram      TEXT,
  slurm_job_id    TEXT,
  synced_at       TEXT,

  started_at      TEXT,
  finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_state ON runs(state);
CREATE INDEX IF NOT EXISTS idx_sample ON runs(sample_id);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  srr TEXT,
  ts TEXT DEFAULT (datetime('now')),
  from_state TEXT,
  to_state TEXT,
  detail TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    if "allow_retry" not in cols:
        conn.execute(
            "ALTER TABLE runs ADD COLUMN allow_retry INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    # PENDING with prior attempts but no explicit retry flag (e.g. old bulk retry-failed).
    conn.execute(
        """
        UPDATE runs SET
          state = 'FAILED',
          last_error = COALESCE(
            NULLIF(trim(last_error), ''),
            'deferred: use kitsune retry-failed after fixing fetch/chemistry'
          )
        WHERE state = 'PENDING' AND attempts > 0 AND allow_retry = 0
        """
    )
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def insert_run(
    conn: sqlite3.Connection,
    *,
    srr: str,
    gse: str,
    sample_id: str,
    srp: str = "",
    donor_id: str | None = None,
    disease: str | None = None,
    tier: str | None = None,
) -> bool:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO runs (srr, gse, srp, sample_id, donor_id, disease, tier)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (srr, gse, srp, sample_id, donor_id, disease, tier),
    )
    conn.commit()
    return cur.rowcount > 0


def _claim_order_sql(
    *,
    smallest_gse_first: bool,
    defer_gse: frozenset[str],
    priority_gse: frozenset[str],
) -> str:
    defer = ",".join(f"'{g}'" for g in sorted(defer_gse))
    defer_case = (
        f"CASE WHEN gse IN ({defer}) THEN 1 ELSE 0 END," if defer_gse else ""
    )
    prio = ",".join(f"'{g}'" for g in sorted(priority_gse))
    priority_case = (
        f"CASE WHEN gse IN ({prio}) THEN 0 ELSE 1 END," if priority_gse else ""
    )
    if smallest_gse_first:
        return f"""
                ORDER BY
                  {priority_case}
                  attempts ASC,
                  {defer_case}
                  (SELECT COUNT(*) FROM runs r2 WHERE r2.gse = runs.gse) ASC,
                  tier, gse, srr
                """
    return f"""
                ORDER BY
                  {priority_case}
                  attempts ASC,
                  {defer_case}
                  tier, gse, srr
                """


def claim_next(
    conn: sqlite3.Connection,
    worker_id: str | None = None,
    *,
    smallest_gse_first: bool = True,
    defer_gse: frozenset[str] | None = None,
    priority_gse: frozenset[str] | None = None,
) -> sqlite3.Row | None:
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    now = _now()
    order = _claim_order_sql(
        smallest_gse_first=smallest_gse_first,
        defer_gse=defer_gse or frozenset(),
        priority_gse=priority_gse or frozenset(),
    )
    for _ in range(64):
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                f"""
                SELECT srr FROM runs
                WHERE state = 'PENDING'
                  AND (attempts = 0 OR allow_retry = 1)
                {order}
                """
            ).fetchone()
            if not row:
                conn.commit()
                return None
            srr = row["srr"]
            cur = conn.execute(
                """
                UPDATE runs SET
                  state = 'CLAIMED',
                  claimed_by = ?,
                  claimed_at = ?,
                  heartbeat_at = ?,
                  attempts = attempts + 1,
                  allow_retry = 0
                WHERE srr = ? AND state = 'PENDING'
                """,
                (worker_id, now, now, srr),
            )
            if cur.rowcount != 1:
                conn.rollback()
                continue
            conn.commit()
            return conn.execute("SELECT * FROM runs WHERE srr = ?", (srr,)).fetchone()
        except Exception:
            conn.rollback()
            raise
    return None


def transition(
    conn: sqlite3.Connection,
    srr: str,
    to_state: str,
    *,
    from_states: tuple[str, ...] | None = None,
    detail: str | None = None,
    **fields: object,
) -> None:
    row = conn.execute("SELECT state FROM runs WHERE srr = ?", (srr,)).fetchone()
    if not row:
        raise KeyError(srr)
    fr = row["state"]
    if from_states and fr not in from_states:
        raise RuntimeError(f"{srr}: cannot go {fr} -> {to_state}")
    sets = ["state = ?"]
    vals: list[object] = [to_state]
    if detail is not None and "last_error" not in fields:
        sets.append("last_error = ?")
        vals.append(detail)
    for k, v in fields.items():
        sets.append(f"{k} = ?")
        vals.append(v)
    vals.append(srr)
    conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE srr = ?", vals)
    conn.execute(
        "INSERT INTO events (srr, from_state, to_state, detail) VALUES (?, ?, ?, ?)",
        (srr, fr, to_state, detail),
    )
    conn.commit()


def heartbeat(conn: sqlite3.Connection, srr: str) -> None:
    conn.execute(
        "UPDATE runs SET heartbeat_at = ? WHERE srr = ?",
        (_now(), srr),
    )
    conn.commit()


def heartbeat_path(db_path: Path, srr: str) -> None:
    """Thread-safe heartbeat (opens its own connection)."""
    conn = connect(db_path)
    try:
        heartbeat(conn, srr)
    finally:
        conn.close()


def reap_stale(conn: sqlite3.Connection, timeout_min: int, max_attempts: int) -> int:
    """Return stale CLAIMED rows to PENDING or QUARANTINE."""
    rows = conn.execute(
        """
        SELECT srr, attempts, heartbeat_at FROM runs
        WHERE state = 'CLAIMED'
        """
    ).fetchall()
    n = 0
    for r in rows:
        hb = r["heartbeat_at"]
        if not hb:
            continue
        # Simple string compare works for ISO UTC from same generator
        # Reaper called periodically; skip complex parsing for v0.1
        conn.execute(
            """
            UPDATE runs SET
              state = CASE WHEN attempts >= ? THEN 'QUARANTINE' ELSE 'PENDING' END,
              claimed_by = NULL,
              allow_retry = 1,
              last_error = COALESCE(last_error, '') || ' reaped stale claim'
            WHERE srr = ? AND state = 'CLAIMED'
              AND (heartbeat_at IS NULL OR heartbeat_at < datetime('now', ?))
            """,
            (max_attempts, r["srr"], f"-{timeout_min} minutes"),
        )
        n += conn.total_changes
    conn.commit()
    return n


def reap_stale_fetching(conn: sqlite3.Connection, timeout_min: int) -> int:
    """Return long-idle FETCHING rows to PENDING (e.g. killed worker mid-prefetch)."""
    conn.execute(
        """
        UPDATE runs SET
          state = 'PENDING',
          claimed_by = NULL,
          allow_retry = 1,
          last_error = COALESCE(last_error, '') || ' reaped stale FETCHING'
        WHERE state = 'FETCHING'
          AND (heartbeat_at IS NULL OR heartbeat_at < datetime('now', ?))
        """,
        (f"-{timeout_min} minutes",),
    )
    n = conn.total_changes
    conn.commit()
    return n


def status_counts(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    return [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT state, COUNT(*) FROM runs GROUP BY state ORDER BY state"
        )
    ]
