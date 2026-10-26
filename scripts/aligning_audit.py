import sqlite3
import subprocess

c = sqlite3.connect("/home/lag1e24/kitsune/ledger/kitsune.db")
rows = c.execute(
    "SELECT gse, srr, slurm_job_id FROM runs WHERE state='ALIGNING'"
).fetchall()
print("aligning", len(rows))
ids = [r[2] for r in rows if r[2]]
if ids:
    j = ",".join(ids)
    p = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-i",
            "/home/lag1e24/.ssh/id_ed25519",
            "lag1e24@loginX001.iridis.soton.ac.uk",
            f"sacct -n -P -j {j} -X --format=JobID,State,ExitCode | sort | uniq -c",
        ],
        capture_output=True,
        text=True,
    )
    print(p.stdout or p.stderr)
for gse, srr, jid in rows[:12]:
    print(gse, srr, jid)
