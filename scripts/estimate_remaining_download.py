#!/usr/bin/env python3
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kitsune_pgx.fetch.ena import filereport_rows, parse_ena_fastqs

import os

DB = Path(os.environ.get("KITSUNE_LEDGER", "kitsune.db"))
NEED = ("PENDING", "CLAIMED", "FETCHING")


def gb(n: int) -> float:
    return n / (1024**3)


def main() -> None:
    conn = sqlite3.connect(DB)
    srrs = [
        r[0]
        for r in conn.execute(
            f"SELECT srr FROM runs WHERE state IN ({','.join('?'*len(NEED))}) ORDER BY srr",
            NEED,
        )
    ]
    done_bytes = [
        r[0]
        for r in conn.execute(
            "SELECT fastq_bytes FROM runs WHERE state='DONE' AND fastq_bytes > 0"
        )
    ]
    print(f"Remaining libraries to fetch: {len(srrs)}")
    if done_bytes:
        print(
            f"Historical DONE: n={len(done_bytes)} median={gb(statistics.median(done_bytes)):.2f} GB "
            f"mean={gb(statistics.mean(done_bytes)):.2f} GB total={gb(sum(done_bytes)):.1f} GB"
        )

    by_gse = conn.execute(
        f"SELECT gse, COUNT(1) FROM runs WHERE state IN ({','.join('?'*len(NEED))}) GROUP BY gse ORDER BY 2 DESC",
        NEED,
    ).fetchall()
    print("By GSE:", ", ".join(f"{g}({n})" for g, n in by_gse))

    if "--ena" not in sys.argv:
        if done_bytes and srrs:
            print(
                f"Rough range @ median–mean: {gb(statistics.median(done_bytes)*len(srrs)):.0f}–"
                f"{gb(statistics.mean(done_bytes)*len(srrs)):.0f} GB (skewed by megastudies)"
            )
        return

    total = 0
    missing = 0
    for i, srr in enumerate(srrs, 1):
        rows = filereport_rows(srr)
        if not rows:
            missing += 1
            continue
        for row in rows:
            for ef in parse_ena_fastqs(row):
                total += ef.nbytes
        if i % 25 == 0 or i == len(srrs):
            print(f"  ENA progress {i}/{len(srrs)} partial sum {gb(total):.1f} GB")
    print(f"ENA exact sum: {gb(total):.1f} GB ({total/1e12:.2f} TB); missing metadata: {missing}")


if __name__ == "__main__":
    main()
