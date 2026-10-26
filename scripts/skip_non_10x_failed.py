#!/usr/bin/env python3
import sqlite3
from pathlib import Path

db = Path("/home/lag1e24/kitsune/ledger/kitsune.db")
conn = sqlite3.connect(db)
cur = conn.execute(
    """
    UPDATE runs SET
      state = 'SKIPPED',
      last_error = 'non-10x paired-end (150+150), not in kitsune scope'
    WHERE state = 'FAILED'
      AND (last_error LIKE '%150%barcode_hits=0%'
           OR last_error LIKE '%non-10x paired-end%')
    """
)
conn.commit()
print(f"skipped {cur.rowcount} FAILED rows")
