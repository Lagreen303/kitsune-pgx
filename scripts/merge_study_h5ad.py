#!/usr/bin/env python3
"""Merge per-sample matrix.h5ad into one AnnData per complete GSE (gencode or noncode only)."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import anndata as ad


FALLBACK_COMPLETE = (
    "GSE147989",
    "GSE174125",
    "GSE182926",
    "GSE183326",
    "GSE244589",
    "GSE291294",
)


def _complete_gses(tsv: Path) -> list[str]:
    if not tsv.is_file():
        return list(FALLBACK_COMPLETE)
    out: list[str] = []
    with tsv.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("analysis_ready") == "Y" or row.get("study_status") == "complete":
                gse = (row.get("gse") or "").strip()
                if gse:
                    out.append(gse)
    return out or list(FALLBACK_COMPLETE)


def merge_one(gse_dir: Path, *, layer: str) -> Path | None:
    """layer is 'gencode' or 'noncode'."""
    parts: list[ad.AnnData] = []
    keys: list[str] = []
    for sample_dir in sorted(p for p in gse_dir.iterdir() if p.is_dir()):
        h5 = sample_dir / layer / "matrix.h5ad"
        prov = sample_dir / "provenance.json"
        if not h5.is_file() or not prov.is_file():
            continue
        a = ad.read_h5ad(h5)
        a.obs["gse"] = gse_dir.name
        if "sample_id" not in a.obs.columns:
            a.obs["sample_id"] = sample_dir.name
        parts.append(a)
        keys.append(sample_dir.name)
    if not parts:
        return None
    merged = ad.concat(
        parts,
        join="inner",
        label="sample_id",
        keys=keys,
        index_unique="-",
    )
    merged.obs["gse"] = gse_dir.name
    out = gse_dir / f"{gse_dir.name}_{layer}_merged.h5ad"
    merged.write_h5ad(out, compression="gzip")
    return out


def _default_scratch_root() -> Path:
    import os

    root = os.environ.get("KITSUNE_ROOT")
    if root:
        return Path(root)
    return Path("/iridisfs/scratch/YOUR_USER/kitsune")


def main() -> None:
    scratch = _default_scratch_root()
    p = argparse.ArgumentParser()
    p.add_argument(
        "--results",
        type=Path,
        default=scratch / "results",
    )
    p.add_argument(
        "--study-tsv",
        type=Path,
        default=scratch / "manifest" / "study_completion.tsv",
    )
    p.add_argument("--gse", action="append", help="Merge only these GSEs (default: analysis_ready=Y)")
    args = p.parse_args()

    gses = args.gse or _complete_gses(args.study_tsv)
    if not gses:
        raise SystemExit("No complete GSEs found (study_completion.tsv missing or empty)")

    for gse in gses:
        gdir = args.results / gse
        if not gdir.is_dir():
            print(f"skip {gse}: no results dir")
            continue
        for layer in ("gencode", "noncode"):
            out = merge_one(gdir, layer=layer)
            if out:
                print(f"wrote {out} ({out.stat().st_size / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
