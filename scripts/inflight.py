import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / "kitsune/ledger/kitsune.db")
for r in c.execute(
    "SELECT srr, state, gse, source, chemistry FROM runs "
    "WHERE state NOT IN ('PENDING','DONE','SKIPPED','FAILED')"
):
    print(r)
print("FAILED", c.execute("SELECT COUNT(1) FROM runs WHERE state='FAILED'").fetchone()[0])
