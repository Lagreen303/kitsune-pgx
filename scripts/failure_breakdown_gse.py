#!/usr/bin/env python3
"""Summarize FAILED run errors from the kitsune ledger."""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import os

DB = Path(os.environ.get("KITSUNE_LEDGER", "kitsune.db"))


def bucket(err: str | None) -> str:
    if not err:
        return "empty"
    e = err.strip()
    if e.startswith("deferred:"):
        return "deferred (bulk retry policy)"
    if "HTTP Error 500" in e:
        return "ENA HTTP 500"
    if "HTTP Error" in e:
        return "ENA HTTP other"
    if "rsync" in e.lower() or "exit code 11" in e or "quota" in e.lower():
        return "rsync / scratch quota"
    if "SLURM job" in e:
        return "SLURM terminal state"
    if "Ambiguous FASTQ" in e or "ambiguous" in e.lower():
        return "ambiguous chemistry / layout"
    if "Need at least 2 FASTQs" in e or "single_fastq" in e.lower():
        return "FASTQ layout (single/3-file)"
    if "prefetch" in e or "fasterq-dump" in e or "vdb-dump" in e:
        return "SRA prefetch/dump"
    if "STAR" in e or "Solo.out" in e or "FATAL ERROR" in e:
        return "STAR / align"
    if "MD5 mismatch" in e:
        return "ENA MD5 mismatch"
    if "wget" in e.lower():
        return "wget / download"
    if "low disk" in e.lower():
        return "PGX low disk"
    if "reaped stale" in e:
        return "reaped stale worker"
    # First line / short prefix
    line = e.split("\n")[0][:120]
    return line if len(line) < 100 else line[:97] + "..."


def main() -> None:
    gse = sys.argv[1] if len(sys.argv) > 1 else None
    conn = sqlite3.connect(DB)
    if gse:
        rows = conn.execute(
            "SELECT srr, substr(last_error,1,500) FROM runs WHERE state='FAILED' AND gse=?",
            (gse,),
        ).fetchall()
        print(f"=== FAILED for {gse}: {len(rows)} ===")
    else:
        rows = conn.execute(
            "SELECT gse, srr, substr(last_error,1,500) FROM runs WHERE state='FAILED'"
        ).fetchall()
        print(f"=== ALL FAILED: {len(rows)} ===")

    ctr: Counter[str] = Counter()
    samples: dict[str, list[str]] = {}
    for row in rows:
        if gse:
            srr, err = row[0], row[1]
            key = bucket(err)
            ctr[key] += 1
            samples.setdefault(key, []).append(srr)
        else:
            g, srr, err = row[0], row[1], row[2]
            key = f"{g} | {bucket(err)}"
            ctr[key] += 1

    for key, n in ctr.most_common(25):
        print(f"  {n:4d}  {key}")
        if gse and key in samples:
            print(f"        e.g. {samples[key][0]}")

    if gse:
        states = conn.execute(
            "SELECT state, COUNT(1) FROM runs WHERE gse=? GROUP BY state ORDER BY 2 DESC",
            (gse,),
        ).fetchall()
        print("\n=== GSE state counts ===")
        for st, n in states:
            print(f"  {st}: {n}")

        recent = conn.execute(
            """
            SELECT srr, substr(last_error,1,200) FROM runs
            WHERE gse=? AND state='FAILED' AND last_error NOT LIKE 'deferred:%'
            ORDER BY srr DESC LIMIT 8
            """,
            (gse,),
        ).fetchall()
        if recent:
            print("\n=== Recent non-deferred FAILED (sample) ===")
            for srr, err in recent:
                print(f"  {srr}: {(err or '')[:180]}")


if __name__ == "__main__":
    main()
