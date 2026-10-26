"""Print per-GSE status for a subset of studies (no shell grep)."""
from __future__ import annotations

import sqlite3
import sys
from typing import TextIO

from kitsune_pgx.study_report import GseRow, _load_gse_rows

_IN_FLIGHT = ("CLAIMED", "FETCHING", "FETCHED", "STAGED", "ALIGNING")


def _gse_rows_for(conn: sqlite3.Connection, gses: frozenset[str]) -> list[GseRow]:
    by = {r.gse: r for r in _load_gse_rows(conn)}
    return [by[g] for g in sorted(gses) if g in by]


def print_study_status(
    conn: sqlite3.Connection,
    gses: frozenset[str],
    *,
    stream: TextIO | None = None,
) -> None:
    out = stream or sys.stdout
    missing = sorted(g for g in gses if g not in {r.gse for r in _load_gse_rows(conn)})
    rows = _gse_rows_for(conn, gses)

    out.write(
        "gse\ttotal_runs\tdone\tfailed\tskipped\tpending\tin_flight\t"
        "study_status\tanalysis_ready\n"
    )
    for r in rows:
        out.write(
            f"{r.gse}\t{r.total}\t{r.done}\t{r.failed}\t{r.skipped}\t"
            f"{r.pending}\t{r.in_flight}\t{r.study_status()}\t{r.analysis_ready()}\n"
        )
    for g in missing:
        out.write(f"{g}\t0\t0\t0\t0\t0\t0\tempty\tN\n")

    if gses:
        ph = ",".join("?" for _ in gses)
        out.write("\n=== by state (selected GSEs) ===\n")
        for gse, state, n in conn.execute(
            f"""
            SELECT gse, state, COUNT(1) FROM runs
            WHERE gse IN ({ph})
            GROUP BY gse, state
            ORDER BY gse, state
            """,
            tuple(sorted(gses)),
        ):
            out.write(f"{gse}\t{state}\t{n}\n")

        out.write("\n=== in-flight runs ===\n")
        states = ",".join(f"'{s}'" for s in _IN_FLIGHT)
        any_row = False
        for srr, gse, state, job in conn.execute(
            f"""
            SELECT srr, gse, state, COALESCE(slurm_job_id, '')
            FROM runs
            WHERE gse IN ({ph}) AND state IN ({states})
            ORDER BY gse, srr
            """,
            tuple(sorted(gses)),
        ):
            any_row = True
            out.write(f"{srr}\t{gse}\t{state}\t{job}\n")
        if not any_row:
            out.write("(none)\n")
