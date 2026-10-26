#!/usr/bin/env python3
"""Summarize FAILED run errors from the ledger."""
import re
import sqlite3
from collections import Counter
from pathlib import Path

db = Path.home() / "kitsune/ledger/kitsune.db"
c = sqlite3.connect(db)
rows = c.execute(
    "SELECT gse, srr, last_error FROM runs WHERE state='FAILED' AND last_error IS NOT NULL"
).fetchall()

BUCKETS = [
    ("single_fastq", re.compile(r"Need at least 2 FASTQs", re.I)),
    ("wget_ena", re.compile(r"wget|filereport|ebi\.ac\.uk", re.I)),
    ("ambiguous_chemistry", re.compile(r"Ambiguous FASTQ roles", re.I)),
    ("sra_tools", re.compile(r"prefetch|fasterq|SRA tools", re.I)),
    ("slurm_align", re.compile(r"SLURM job|sbatch", re.I)),
    ("md5", re.compile(r"MD5 mismatch", re.I)),
    ("low_disk", re.compile(r"low disk", re.I)),
]


def bucket(err: str) -> str:
    for name, pat in BUCKETS:
        if pat.search(err):
            return name
    return "other"


counts = Counter()
by_bucket_gse: dict[str, Counter] = {}
examples: dict[str, list] = {}

for gse, srr, err in rows:
    b = bucket(err or "")
    counts[b] += 1
    by_bucket_gse.setdefault(b, Counter())[gse] += 1
    examples.setdefault(b, [])
    if len(examples[b]) < 2:
        examples[b].append((gse, srr, (err or "")[:160]))

print(f"FAILED with last_error: {len(rows)}")
print("\n=== By category ===")
for b, n in counts.most_common():
    print(f"{n:4d}  {b}")
    for gse, gn in by_bucket_gse[b].most_common(5):
        print(f"       {gse}: {gn}")
    for gse, srr, ex in examples[b][:1]:
        print(f"       e.g. {srr}: {ex}")

print("\n=== Top raw messages ===")
raw = Counter()
for _, _, err in rows:
    key = (err or "")[:120]
    raw[key] += 1
for msg, n in raw.most_common(12):
    print(f"{n:4d}  {msg}")
