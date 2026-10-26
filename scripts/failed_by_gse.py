#!/usr/bin/env python3
import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / "kitsune/ledger/kitsune.db")
print("=== GSEs with any FAILED (failed/done/pending/total) ===")
for r in c.execute(
    """
    SELECT gse,
      SUM(state='FAILED'),
      SUM(state='DONE'),
      SUM(state='PENDING'),
      COUNT(1)
    FROM runs GROUP BY gse
    HAVING SUM(state='FAILED') > 0
    ORDER BY SUM(state='FAILED') DESC, gse
    """
):
    print(f"{r[0]}\tfailed={r[1]}\tdone={r[2]}\tpending={r[3]}\ttotal={r[4]}")

print("\n=== GSEs where ALL runs FAILED (none done/pending) ===")
for r in c.execute(
    """
    SELECT gse, COUNT(1) FROM runs
    GROUP BY gse
    HAVING SUM(state='FAILED') = COUNT(1)
    """
):
    print(r)

print("\n=== GSEs with both DONE and FAILED ===")
for r in c.execute(
    """
    SELECT gse, SUM(state='FAILED'), SUM(state='DONE')
    FROM runs GROUP BY gse
    HAVING SUM(state='FAILED') > 0 AND SUM(state='DONE') > 0
    """
):
    print(r)
