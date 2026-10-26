#!/usr/bin/env python3
"""Donor / sample counts for analysis-ready GSEs."""
import csv
import sqlite3
from pathlib import Path

COMPLETE = (
    "GSE147989",
    "GSE174125",
    "GSE182926",
    "GSE183326",
    "GSE244589",
    "GSE291294",
)

db = sqlite3.connect(Path.home() / "kitsune/ledger/kitsune.db")
cohort = Path.home() / "kitsune/manifest/cohort_studies.tsv"
if not cohort.is_file():
    cohort = Path.home() / "kitsune-pgx/manifest/cohort_studies.tsv"

print("=== From ledger (DONE runs) ===")
for gse in COMPLETE:
    row = db.execute(
        """
        SELECT COUNT(1),
               COUNT(DISTINCT sample_id),
               COUNT(DISTINCT donor_id),
               COUNT(DISTINCT donor_id) FILTER (WHERE donor_id IS NOT NULL AND donor_id != '')
        FROM runs WHERE gse=? AND state='DONE'
        """,
        (gse,),
    ).fetchone()
    print(f"{gse}: runs={row[0]} sample_ids={row[1]} donor_id_distinct={row[3]}")

all_d = db.execute(
    """
    SELECT COUNT(DISTINCT donor_id) FROM runs
    WHERE gse IN ({}) AND state='DONE'
      AND donor_id IS NOT NULL AND donor_id != ''
    """.format(",".join("?" * len(COMPLETE))),
    COMPLETE,
).fetchone()[0]
print(f"distinct donor_id across complete GSEs (ledger): {all_d}")

print("\n=== Cohort manifest (study-level 'donors' column) ===")
with cohort.open(encoding="utf-8") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        if row["gse"] in COMPLETE:
            print(
                f"{row['gse']}: donors_col={row['donors']} "
                f"runs_col={row['runs']} biosamples_col={row['biosamples']} "
                f"| {row['breakdown'][:80]}"
            )
