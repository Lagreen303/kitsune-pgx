from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StudyRow:
    tier: str
    gse: str
    srp: str
    bioproject: str
    disease: str
    status: str
    title: str


def normalize_tier(raw: str) -> str:
    m = re.match(r"^\s*([0-9Xx])", raw.strip())
    if m:
        return m.group(1).upper()
    return raw.strip()


def load_studies(path: Path) -> list[StudyRow]:
    studies: list[StudyRow] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            studies.append(
                StudyRow(
                    tier=normalize_tier(row["tier"]),
                    gse=row["gse"].strip(),
                    srp=row["sra"].strip(),
                    bioproject=row["bioproject"].strip(),
                    disease=row.get("disease", "").strip(),
                    status=row.get("status", "TO_DOWNLOAD").strip(),
                    title=row.get("title", "").strip(),
                )
            )
    return studies


def filter_studies(
    studies: list[StudyRow],
    *,
    skip_tier_x: bool,
    skip_already_processed: bool,
) -> list[StudyRow]:
    out: list[StudyRow] = []
    for s in studies:
        if skip_tier_x and s.tier == "X":
            continue
        if skip_already_processed and s.status.upper() == "ALREADY_PROCESSED":
            continue
        if s.status.upper() != "TO_DOWNLOAD" and skip_already_processed:
            continue
        out.append(s)
    return out
