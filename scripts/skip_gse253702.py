import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / "kitsune/ledger/kitsune.db")
c.execute(
    """
    UPDATE runs SET state='SKIPPED', last_error='exclude_gse GSE253702 non-10x'
    WHERE gse='GSE253702' AND state IN ('FAILED', 'PENDING')
    """
)
c.commit()
print("updated", c.total_changes)
