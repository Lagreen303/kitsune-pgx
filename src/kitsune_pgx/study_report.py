"""Per-GSE pipeline completion report from the SQLite ledger."""
from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


STATES = (
    "PENDING",
    "CLAIMED",
    "FETCHING",
    "FETCHED",
    "STAGED",
    "ALIGNING",
    "DONE",
    "FAILED",
    "SKIPPED",
    "QUARANTINE",
)


@dataclass(frozen=True)
class GseRow:
    gse: str
    total: int
    counts: dict[str, int]
    top_failure: str

    @property
    def done(self) -> int:
        return self.counts.get("DONE", 0)

    @property
    def failed(self) -> int:
        return self.counts.get("FAILED", 0)

    @property
    def skipped(self) -> int:
        return self.counts.get("SKIPPED", 0)

    @property
    def in_flight(self) -> int:
        return sum(
            self.counts.get(s, 0)
            for s in ("CLAIMED", "FETCHING", "FETCHED", "STAGED", "ALIGNING")
        )

    @property
    def pending(self) -> int:
        return self.counts.get("PENDING", 0)

    def _active_runs(self) -> int:
        return self.total - self.skipped

    def study_status(self) -> str:
        """High-level label for filtering and dashboards."""
        if self.total == 0:
            return "empty"
        if self.skipped == self.total:
            return "skipped_all"
        active = self._active_runs()
        if (
            self.done == active
            and self.failed == 0
            and self.in_flight == 0
            and self.pending == 0
        ):
            return "complete"
        if (
            self.failed == active
            and self.done == 0
            and self.in_flight == 0
            and self.pending == 0
        ):
            return "failed_all"
        if self.in_flight > 0 or self.pending > 0:
            return "in_progress"
        if self.done > 0 and self.failed > 0:
            return "partial"
        return "other"

    def analysis_ready(self) -> str:
        """Y if every non-skipped run is DONE (no FAILED / in-flight / pending)."""
        return "Y" if self.study_status() == "complete" else "N"


def _load_gse_rows(conn: sqlite3.Connection) -> list[GseRow]:
    by_gse: dict[str, dict[str, int]] = {}
    for gse, state, n in conn.execute(
        "SELECT gse, state, COUNT(1) FROM runs GROUP BY gse, state"
    ):
        by_gse.setdefault(gse, {})[state] = n

    failures: dict[str, str] = {}
    for gse, err, n in conn.execute(
        """
        SELECT gse, substr(COALESCE(last_error, ''), 1, 200), COUNT(1)
        FROM runs WHERE state = 'FAILED' AND last_error IS NOT NULL
        GROUP BY gse, substr(COALESCE(last_error, ''), 1, 200)
        ORDER BY gse, COUNT(1) DESC
        """
    ):
        if gse not in failures:
            failures[gse] = f"{n}x {err}"

    rows: list[GseRow] = []
    for gse in sorted(by_gse):
        counts = by_gse[gse]
        total = sum(counts.values())
        rows.append(
            GseRow(
                gse=gse,
                total=total,
                counts=counts,
                top_failure=failures.get(gse, ""),
            )
        )
    return rows


def write_study_completion_tsv(path: Path, conn: sqlite3.Connection) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _load_gse_rows(conn)
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    fieldnames = [
        "gse",
        "total_runs",
        "done",
        "failed",
        "skipped",
        "pending",
        "in_flight",
        "study_status",
        "analysis_ready",
        "top_failure_summary",
        "generated_at_utc",
    ]
    for s in STATES:
        if s not in fieldnames and s not in ("DONE", "FAILED", "SKIPPED", "PENDING"):
            pass  # detail columns optional

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "gse": r.gse,
                    "total_runs": r.total,
                    "done": r.done,
                    "failed": r.failed,
                    "skipped": r.skipped,
                    "pending": r.pending,
                    "in_flight": r.in_flight,
                    "study_status": r.study_status(),
                    "analysis_ready": r.analysis_ready(),
                    "top_failure_summary": r.top_failure,
                    "generated_at_utc": generated,
                }
            )
    return len(rows)
