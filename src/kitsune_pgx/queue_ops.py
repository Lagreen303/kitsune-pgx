from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from kitsune_pgx.cohort import StudyRow, filter_studies, load_studies
from kitsune_pgx.fetch.runinfo import fetch_runinfo_csv, load_runinfo_csv
from kitsune_pgx.ledger import connect, insert_run


def queue_gse(
    conn: sqlite3.Connection,
    manifest_dir: Path,
    *,
    gse: str,
    bioproject: str,
    srp: str = "",
    disease: str = "",
    tier: str = "",
    iridis_runinfo_dir: Path | None = None,
) -> tuple[int, int]:
    """Fetch or reuse runinfo CSV, insert runs into ledger. Returns (runs_in_csv, newly_inserted)."""
    csv_path = manifest_dir / "runinfo" / f"{gse}_sra.csv"
    if iridis_runinfo_dir:
        legacy = iridis_runinfo_dir / f"{gse}_sra.csv"
        if legacy.is_file() and not csv_path.is_file():
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_bytes(legacy.read_bytes())
    if not csv_path.is_file():
        fetch_runinfo_csv(bioproject=bioproject, gse=gse, out_path=csv_path)

    rows = load_runinfo_csv(csv_path)
    new = 0
    for srr, gse_col, sample_id in rows:
        if insert_run(
            conn,
            srr=srr,
            gse=gse_col,
            sample_id=sample_id,
            srp=srp,
            disease=disease or None,
            tier=tier or None,
        ):
            new += 1
    return len(rows), new


def queue_studies_from_manifest(
    conn: sqlite3.Connection,
    studies_path: Path,
    manifest_dir: Path,
    *,
    skip_tier_x: bool,
    skip_already_processed: bool,
    iridis_runinfo_dir: Path | None = None,
) -> list[tuple[str, int, int]]:
    studies = filter_studies(
        load_studies(studies_path),
        skip_tier_x=skip_tier_x,
        skip_already_processed=skip_already_processed,
    )
    # Only TO_DOWNLOAD
    studies = [s for s in studies if s.status.upper() == "TO_DOWNLOAD"]
    summary: list[tuple[str, int, int]] = []
    errors: list[tuple[str, str]] = []
    for s in studies:
        try:
            total, new = queue_gse(
                conn,
                manifest_dir,
                gse=s.gse,
                bioproject=s.bioproject,
                srp=s.srp,
                disease=s.disease,
                tier=s.tier,
                iridis_runinfo_dir=iridis_runinfo_dir,
            )
            summary.append((s.gse, total, new))
        except Exception as e:
            errors.append((s.gse, str(e)[:500]))
        time.sleep(0.34)
    if errors:
        import sys

        for gse, msg in errors:
            print(f"ERROR {gse}: {msg}", file=sys.stderr)
        if not summary:
            raise RuntimeError(f"queue-studies failed for all {len(errors)} studies")
    return summary
