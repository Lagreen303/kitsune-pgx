#!/usr/bin/env python3
import sqlite3
from pathlib import Path

db = Path.home() / "kitsune/ledger/kitsune.db"
c = sqlite3.connect(db)
print("=== by state ===")
for r in c.execute("SELECT state, COUNT(*) FROM runs GROUP BY state ORDER BY state"):
    print(f"{r[0]}\t{r[1]}")
print("\n=== in flight ===")
for r in c.execute(
    "SELECT srr, state, gse FROM runs WHERE state IN ('FETCHING','ALIGNING','CLAIMED','STAGED')"
):
    print(r)
print("\n=== top failures ===")
for r in c.execute(
    """
    SELECT COUNT(*), substr(COALESCE(last_error,''),1,120)
    FROM runs WHERE state='FAILED'
    GROUP BY substr(COALESCE(last_error,''),1,120)
    ORDER BY COUNT(*) DESC LIMIT 8
    """
):
    print(f"{r[0]}x\t{r[1]}")
