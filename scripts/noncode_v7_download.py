#!/usr/bin/env python3
"""Download NONCODE v7 pre-aligned scRNA bundles (Cell Ranger-style .tar per GSE).

The v7 web UI is a Vue SPA; bulk files are not on Zenodo (only code.ipynb ~9 MB).
Catalog:  GET https://v7.noncode.org/single-cell/api/datasets.php
Per-GSE:   GET https://v7.noncode.org/GSE_Download/{GSE}.tar

v7.noncode.org currently serves an **expired TLS certificate** — browsers block it.
Use curl/wget with insecure TLS (this script does) or fix verify after they renew.

Overlap with kitsune-pgx: same GEO studies may appear in both; NONCODE v7 used
Cell Ranger 8.0.1 on NONCODE v6 + Ensembl protein-coding — not identical to our
STARsolo NONCODE v6 index, but useful as an alternative precomputed lncRNA layer.

Examples:
  python scripts/noncode_v7_download.py --list
  python scripts/noncode_v7_download.py --gse GSE147989 --out /data/noncode_v7
  python scripts/noncode_v7_download.py --from-tsv manifest/cohort_studies.tsv --out ./noncode_v7
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://v7.noncode.org"
CATALOG = f"{BASE}/single-cell/api/datasets.php"

# NONCODE v7 catalog category labels (datasets.php).
COHORT_PBMC_HEALTHY = "Healthy human peripheral blood"
COHORT_HEMATOLOGICAL = "Hematological diseases"
COHORTS_PBMC_HEMA = (COHORT_PBMC_HEALTHY, COHORT_HEMATOLOGICAL)

MANIFEST_FIELDS = (
    "gse",
    "cohort",
    "category",
    "tissue",
    "disease",
    "title",
    "tar_available",
    "tar_bytes",
    "tar_url",
)

_PBMC_TISSUE_RE = re.compile(
    r"(?<![a-z])pbmc(?![a-z])"
    r"|peripheral\s*blood\s*mononuclear"
    r"|(?<![a-z])pbmcs(?![a-z])"
    r"|peripheral\s*blood\s*\(",  # e.g. Peripheral blood (pDCs)
    re.IGNORECASE,
)
_PERIPHERAL_NERVES_RE = re.compile(r"peripheral\s+nerves", re.IGNORECASE)


def is_pbmc_tissue(tissue: str) -> bool:
    """True if tissue field denotes PBMC (including compound GEO labels)."""
    t = (tissue or "").strip()
    if not t or _PERIPHERAL_NERVES_RE.search(t):
        return False
    if _PBMC_TISSUE_RE.search(t):
        return True
    for part in re.split(r"[;,/|]", t):
        part = part.strip()
        if not part:
            continue
        if _PBMC_TISSUE_RE.search(part):
            return True
        low = part.lower()
        if low in (
            "peripheral blood mononuclear cell",
            "peripheral blood mononuclear cells",
            "peripheral blood mononuclear cell(pbmc)",
        ):
            return True
    return False


def is_healthy_disease(disease: str) -> bool:
    d = (disease or "").strip().lower()
    if not d:
        return False
    if d in ("healthy", "health", "health_adult", "health adult"):
        return True
    if d.startswith("healthy"):
        return True
    if "healthy" in d and "unhealthy" not in d:
        return True
    return False


def _insecure_ctx() -> ssl.SSLContext:
    return ssl._create_unverified_context()


def fetch_catalog() -> list[dict[str, str]]:
    req = urllib.request.Request(
        CATALOG,
        headers={"User-Agent": "kitsune-pgx/noncode_v7_download"},
    )
    with urllib.request.urlopen(req, context=_insecure_ctx(), timeout=120) as resp:
        payload = json.loads(resp.read().decode())
    data = payload.get("data") or {}
    return list(data.get("list") or [])


def tar_url(gse: str) -> str:
    return f"{BASE}/GSE_Download/{gse}.tar"


def head_ok(url: str) -> tuple[bool, int | None]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "kitsune-pgx"})
    try:
        with urllib.request.urlopen(req, context=_insecure_ctx(), timeout=60) as resp:
            cl = resp.headers.get("Content-Length")
            return True, int(cl) if cl else None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        raise


def download_tar(gse: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{gse}.tar"
    url = tar_url(gse)
    ok, nbytes = head_ok(url)
    if not ok:
        raise FileNotFoundError(f"No bundle at {url} (404)")
    cmd = [
        "curl",
        "-fSkL",
        "--retry",
        "5",
        "--retry-delay",
        "30",
        "-C",
        "-",
        "-o",
        str(out),
        url,
    ]
    subprocess.run(cmd, check=True)
    if nbytes and out.stat().st_size != nbytes:
        print(
            f"warning: {gse} size {out.stat().st_size} != Content-Length {nbytes}",
            file=sys.stderr,
        )
    return out


def select_pbmc_hema(rows: list[dict[str, str]]) -> list[tuple[dict[str, str], str]]:
    """Return (catalog row, cohort tag) for PBMC healthy + hematological diseases."""
    picked: dict[str, tuple[dict[str, str], str]] = {}

    def add(row: dict[str, str], cohort: str) -> None:
        gse = (row.get("Dataset") or "").strip()
        if not gse:
            return
        if gse not in picked or cohort == COHORT_HEMATOLOGICAL:
            picked[gse] = (row, cohort)

    for r in rows:
        cat = (r.get("Category") or "").strip()
        if cat == COHORT_HEMATOLOGICAL:
            add(r, "hematological")
            continue
        if cat == COHORT_PBMC_HEALTHY:
            add(r, "pbmc_healthy")
            continue
        if is_pbmc_tissue(r.get("Tissue") or "") and is_healthy_disease(
            r.get("Disease") or ""
        ):
            add(r, "pbmc_healthy")

    return list(picked.values())


def probe_row(
    row: dict[str, str], cohort: str, delay_s: float = 0.15
) -> dict[str, str]:
    gse = (row.get("Dataset") or "").strip()
    url = tar_url(gse)
    ok, nbytes = head_ok(url)
    time.sleep(delay_s)
    return {
        "gse": gse,
        "cohort": cohort,
        "category": row.get("Category") or "",
        "tissue": row.get("Tissue") or "",
        "disease": row.get("Disease") or "",
        "title": row.get("Title") or "",
        "tar_available": "Y" if ok else "N",
        "tar_bytes": str(nbytes or ""),
        "tar_url": url,
    }


def write_manifest(path: Path, rows: list[tuple[dict[str, str], str]]) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    probed = [probe_row(r, cohort) for r, cohort in rows]
    viable = [r for r in probed if r["tar_available"] == "Y"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows(probed)
    return len(probed), len(viable)


def read_manifest(path: Path) -> list[str]:
    gses: list[str] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("tar_available") == "Y":
                g = (row.get("gse") or "").strip()
                if g:
                    gses.append(g)
    return sorted(set(gses))


def gses_from_tsv(path: Path) -> list[str]:
    gses: list[str] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            g = (row.get("gse") or "").strip()
            if g.startswith("GSE"):
                gses.append(g)
    return sorted(set(gses))


def main() -> None:
    p = argparse.ArgumentParser(description="Download NONCODE v7 GSE_Download/*.tar")
    p.add_argument("--list", action="store_true", help="Print catalog GSE IDs")
    p.add_argument("--gse", action="append", help="GSE accession (repeatable)")
    p.add_argument(
        "--from-tsv",
        type=Path,
        help="Extract gse column from a TSV (e.g. cohort_studies.tsv)",
    )
    p.add_argument("--out", type=Path, default=Path("noncode_v7_downloads"))
    p.add_argument(
        "--probe",
        action="store_true",
        help="Only check which tars exist (HEAD), do not download",
    )
    p.add_argument(
        "--cohort",
        choices=["pbmc-healthy-and-hema"],
        help="Select catalog subset (PBMC healthy + hematological diseases)",
    )
    p.add_argument(
        "--write-manifest",
        type=Path,
        metavar="TSV",
        help="Probe tar availability and write manifest TSV",
    )
    p.add_argument(
        "--download-manifest",
        type=Path,
        metavar="TSV",
        help="Download all tar_available=Y rows from manifest",
    )
    args = p.parse_args()

    catalog = fetch_catalog()
    catalog_gses = {r["Dataset"] for r in catalog if r.get("Dataset")}

    if args.cohort == "pbmc-healthy-and-hema" and args.write_manifest:
        selected = select_pbmc_hema(catalog)
        n, viable = write_manifest(args.write_manifest, selected)
        print(
            f"Wrote {args.write_manifest}: {n} catalog rows, {viable} with downloadable .tar",
            file=sys.stderr,
        )
        return

    if args.download_manifest:
        for gse in read_manifest(args.download_manifest):
            try:
                path = download_tar(gse, args.out)
                print(f"OK {path}")
            except FileNotFoundError as e:
                print(f"SKIP {gse}: {e}", file=sys.stderr)
            except subprocess.CalledProcessError as e:
                print(f"FAIL {gse}: curl exit {e.returncode}", file=sys.stderr)
        return

    if args.list:
        for r in catalog:
            print(r.get("Dataset"), r.get("Category"), r.get("Disease", "")[:40])
        print(f"\n{catalog_gses.__len__()} studies in catalog", file=sys.stderr)
        return

    targets: list[str] = []
    if args.gse:
        targets.extend(g.strip() for g in args.gse if g and g.strip())
    if args.from_tsv:
        targets.extend(gses_from_tsv(args.from_tsv))
    if args.cohort == "pbmc-healthy-and-hema":
        selected = select_pbmc_hema(catalog)
        targets.extend((r.get("Dataset") or "").strip() for r, _ in selected)

    if not targets:
        p.error("pass --gse, --from-tsv, --cohort, --write-manifest, or --list")

    targets = sorted(set(targets))
    missing_cat = [g for g in targets if g not in catalog_gses]
    if missing_cat:
        print("not in NONCODE v7 catalog:", ", ".join(missing_cat), file=sys.stderr)

    for gse in targets:
        url = tar_url(gse)
        if args.probe:
            ok, nbytes = head_ok(url)
            size = f"{nbytes / 1e6:.1f} MB" if nbytes else "?"
            print(f"{gse}\t{'OK' if ok else 'MISSING'}\t{size}\t{url}")
            continue
        try:
            path = download_tar(gse, args.out)
            print(f"OK {path}")
        except FileNotFoundError as e:
            print(f"SKIP {gse}: {e}", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"FAIL {gse}: curl exit {e.returncode}", file=sys.stderr)


if __name__ == "__main__":
    main()
