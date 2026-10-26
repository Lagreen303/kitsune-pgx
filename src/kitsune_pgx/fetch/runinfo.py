"""Build srr,gse,sample_id CSV from NCBI SRA runinfo (ported from Iridis download_align_data)."""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def _http_get(url: str, *, retries: int = 6) -> bytes:
    req = Request(
        url,
        headers={"User-Agent": "kitsune-pgx/0.1"},
    )
    delay = 0.5
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=120) as resp:
                return resp.read()
        except HTTPError as e:
            if e.code == 429 and attempt + 1 < retries:
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            raise
    raise RuntimeError("unreachable")


def fetch_runinfo_csv(*, bioproject: str, gse: str, out_path: Path) -> int:
    bp = quote(bioproject, safe="")
    esearch = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=sra&term={bp}&retmax=2000&retmode=json"
    )
    ids = json.loads(_http_get(esearch).decode())["esearchresult"]["idlist"]
    if not ids:
        raise ValueError(f"No SRA ids for bioproject {bioproject!r}")

    time.sleep(0.34)

    efetch = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=sra&id={','.join(ids)}&rettype=runinfo&retmode=text"
    )
    text = _http_get(efetch).decode()
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise ValueError("Empty runinfo from efetch")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["srr", "gse", "sample_id"])
        for r in sorted(rows, key=lambda x: x["Run"]):
            gsm = (r.get("SampleName") or "").strip() or "sample"
            srr = r["Run"].strip()
            w.writerow([srr, gse, f"{gsm}_{srr}"])
    return len(rows)


def load_runinfo_csv(path: Path) -> list[tuple[str, str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return [(row["srr"], row["gse"], row["sample_id"]) for row in r]
