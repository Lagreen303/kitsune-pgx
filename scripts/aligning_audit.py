import os
import sqlite3
import subprocess
from pathlib import Path

from kitsune_pgx.config import load_config
from kitsune_pgx.sync.iridis import _ssh_base

cfg_path = Path(os.environ.get("KITSUNE_CONFIG", "config.pgx.yaml"))
cfg = load_config(cfg_path)
ledger = Path(os.environ.get("KITSUNE_LEDGER", cfg.ledger_path))

c = sqlite3.connect(ledger)
rows = c.execute(
    "SELECT gse, srr, slurm_job_id FROM runs WHERE state='ALIGNING'"
).fetchall()
print("aligning", len(rows))
ids = [r[2] for r in rows if r[2]]
if ids:
    j = ",".join(ids)
    ssh_cmd = _ssh_base(cfg) + [
        f"sacct -n -P -j {j} -X --format=JobID,State,ExitCode | sort | uniq -c",
    ]
    p = subprocess.run(ssh_cmd, capture_output=True, text=True)
    print(p.stdout or p.stderr)
for gse, srr, jid in rows[:12]:
    print(gse, srr, jid)
