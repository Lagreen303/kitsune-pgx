#!/usr/bin/env python3
"""Print ledger + study_completion summary for config priority_gse (run on PGX)."""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

from kitsune_pgx.config import load_config
from kitsune_pgx.study_report import _load_gse_rows


def main() -> None:
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "kitsune-pgx/config.pgx.yaml"
    cfg = load_config(cfg_path)
    prio = sorted(cfg.priority_gse)
    if not prio:
        print("priority_gse is empty in config", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(cfg.ledger_path)
    conn.row_factory = sqlite3.Row
    by_gse = {r.gse: r for r in _load_gse_rows(conn)}

    print("=== priority GSE (ledger) ===")
    ph = ",".join("?" * len(prio))
    for gse, state, n in conn.execute(
        f"SELECT gse, state, COUNT(*) FROM runs WHERE gse IN ({ph}) "
        "GROUP BY gse, state ORDER BY gse, state",
        prio,
    ):
        print(f"{gse}\t{state}\t{n}")

    print("=== in-flight (priority) ===")
    for row in conn.execute(
        f"SELECT srr, gse, state, slurm_job_id FROM runs "
        f"WHERE gse IN ({ph}) AND state IN "
        "('CLAIMED','FETCHING','FETCHED','STAGED','ALIGNING')",
        prio,
    ):
        print(dict(row))

    tsv = cfg.manifest_path / "study_completion.tsv"
    print(f"=== study_completion.tsv ({tsv.name}) ===")
    if tsv.is_file():
        with tsv.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            print("\t".join(reader.fieldnames or []))
            for row in reader:
                if row.get("gse") in prio:
                    print("\t".join(row.get(h, "") for h in reader.fieldnames or []))
    else:
        print("(missing — run kitsune study-report)")

    conn.close()


if __name__ == "__main__":
    main()
