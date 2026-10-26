#!/usr/bin/env python3
"""Single-sample dual STARsolo + h5ad on Iridis (run inside apptainer)."""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _tool(name: str, env_key: str) -> str:
    return os.environ.get(env_key) or shutil.which(name) or name


def _resolve_fastq(staging: Path, name: str) -> Path:
    for cand in (staging / "fastq" / name, staging / name):
        if cand.is_file():
            return cand
    raise FileNotFoundError(f"FASTQ {name!r} not under {staging} or {staging}/fastq")


def _read_meta(staging: Path) -> dict:
    p = staging / "fetch_meta.json"
    if not p.is_file():
        raise FileNotFoundError(f"Missing {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _plain_whitelist(path: Path, work: Path) -> Path:
    if path.suffix == ".gz" or path.name.endswith(".gz"):
        out = work / "whitelist.txt"
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fin:
            out.write_text(fin.read(), encoding="utf-8")
        return out
    return path


def _prune_star_artifacts(sample_out: Path) -> None:
    """Drop STARsolo trees and BAMs after h5ad export (keep matrix.h5ad)."""
    for sub in ("gencode", "noncode"):
        d = sample_out / sub
        if not d.is_dir():
            continue
        for p in list(d.iterdir()):
            if p.is_dir() and p.name.endswith("_Solo.out"):
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file() and (
                p.name.endswith(("_Log.final.out", "_Log.out", "_Log.progress.out", "_SJ.out.tab"))
                or "Aligned.sortedByCoord.out.bam" in p.name
            ):
                p.unlink(missing_ok=True)


def _solo_mtx(out_prefix: Path) -> Path:
    # Matches --soloFeatures GeneFull
    return Path(f"{out_prefix}_Solo.out") / "GeneFull" / "filtered"


def _mtx_to_h5ad(mtx_dir: Path, out_h5ad: Path, sample_id: str, srr: str) -> None:
    import anndata as ad
    import pandas as pd
    from scipy.io import mmread

    features = pd.read_csv(mtx_dir / "features.tsv", sep="\t", header=None)
    barcodes = pd.read_csv(mtx_dir / "barcodes.tsv", sep="\t", header=None)
    X = mmread(mtx_dir / "matrix.mtx").tocsr().T.tocsr()
    if features.shape[1] >= 2:
        var_names = features.iloc[:, 1].astype(str).values
        gene_ids = features.iloc[:, 0].astype(str).values
    else:
        var_names = features.iloc[:, 0].astype(str).values
        gene_ids = None
    adata = ad.AnnData(X=X)
    adata.obs_names = barcodes.iloc[:, 0].astype(str).values
    adata.var_names = var_names
    if gene_ids is not None:
        adata.var["gene_ids"] = gene_ids
    adata.var_names_make_unique()
    adata.obs["sample_id"] = sample_id
    adata.obs["srr"] = srr
    out_h5ad.parent.mkdir(parents=True, exist_ok=True)
    adata.write_h5ad(out_h5ad, compression="gzip")


def run_star(
    *,
    genome_dir: Path,
    r1: Path,
    r2: Path,
    whitelist: Path,
    umi_len: int,
    out_prefix: Path,
    work: Path,
    threads: int,
    emit_bam: bool,
) -> None:
    tmp_root = os.environ.get("STAR_TMPDIR") or os.environ.get("SLURM_TMPDIR")
    if tmp_root:
        star_tmp = Path(tmp_root)
    else:
        star_tmp = work / "star_tmp"
    # STAR creates --outTmpDir itself; it fails if the path already exists.
    shutil.rmtree(star_tmp, ignore_errors=True)
    star_tmp.parent.mkdir(parents=True, exist_ok=True)
    rfc = "zcat" if str(r1).endswith(".gz") else "cat"
    bam_args: list[str] = (
        ["--outSAMtype", "BAM", "SortedByCoordinate", "--outSAMattributes", "NH", "HI", "AS", "nM", "CB", "UB"]
        if emit_bam
        else ["--outSAMtype", "None"]
    )
    star = _tool("STAR", "STAR_BIN")
    cmd = [
        star,
        "--genomeDir",
        str(genome_dir),
        "--readFilesIn",
        str(r2),
        str(r1),
        "--readFilesCommand",
        rfc,
        "--soloType",
        "CB_UMI_Simple",
        "--soloCBwhitelist",
        str(whitelist),
        "--soloCBlen",
        "16",
        "--soloUMIlen",
        str(umi_len),
        "--soloBarcodeReadLength",
        "0",
        "--soloCBmatchWLtype",
        "1MM_multi_Nbase_pseudocounts",
        "--soloUMIdedup",
        "1MM_CR",
        "--soloUMIfiltering",
        "MultiGeneUMI_CR",
        "--soloFeatures",
        "GeneFull",
        "--soloCellFilter",
        "EmptyDrops_CR",
        "--outTmpDir",
        str(star_tmp),
        "--outFileNamePrefix",
        str(out_prefix) + "_",
        "--runThreadN",
        str(threads),
        *bam_args,
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--staging", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--gse", required=True)
    p.add_argument("--srr", required=True)
    p.add_argument("--sample-id", required=True)
    p.add_argument("--gencode-idx", type=Path, required=True)
    p.add_argument("--noncode-idx", type=Path, required=True)
    p.add_argument("--wl-v2", type=Path, required=True)
    p.add_argument("--wl-v3", type=Path, required=True)
    p.add_argument("--ref-fa", type=Path, required=True)
    p.add_argument("--threads", type=int, default=16)
    args = p.parse_args()

    meta = _read_meta(args.staging)
    r1 = _resolve_fastq(args.staging, meta["r1"])
    r2 = _resolve_fastq(args.staging, meta["r2"])

    wl_src = args.wl_v2 if meta["chemistry"] == "v2" else args.wl_v3
    whitelist = _plain_whitelist(wl_src, args.work)
    umi_len = int(meta["umi_len"])

    gencode_out = args.out / "gencode"
    noncode_out = args.out / "noncode"
    audit_out = args.out / "audit"
    gencode_out.mkdir(parents=True, exist_ok=True)
    noncode_out.mkdir(parents=True, exist_ok=True)
    audit_out.mkdir(parents=True, exist_ok=True)

    g_prefix = gencode_out / args.srr
    run_star(
        genome_dir=args.gencode_idx,
        r1=r1,
        r2=r2,
        whitelist=whitelist,
        umi_len=umi_len,
        out_prefix=g_prefix,
        work=args.work,
        threads=args.threads,
        emit_bam=True,
    )
    bam = Path(str(g_prefix) + "_Aligned.sortedByCoord.out.bam")
    if bam.is_file() and not os.environ.get("KITSUNE_SKIP_SAMTOOLS"):
        samtools = _tool("samtools", "SAMTOOLS_BIN")
        subprocess.run([samtools, "index", str(bam)], check=True)
        cram = audit_out / f"{args.sample_id}.loci.cram"
        subprocess.run(
            [samtools, "view", "-C", "-T", str(args.ref_fa), "-o", str(cram), str(bam)],
            check=True,
        )
        subprocess.run([samtools, "index", str(cram)], check=True)
        bam.unlink(missing_ok=True)
        Path(str(bam) + ".bai").unlink(missing_ok=True)

    _mtx_to_h5ad(
        _solo_mtx(g_prefix),
        gencode_out / "matrix.h5ad",
        args.sample_id,
        args.srr,
    )

    nc_prefix = noncode_out / args.srr
    run_star(
        genome_dir=args.noncode_idx,
        r1=r1,
        r2=r2,
        whitelist=whitelist,
        umi_len=umi_len,
        out_prefix=nc_prefix,
        work=args.work / "noncode_star",
        threads=args.threads,
        emit_bam=False,
    )
    _mtx_to_h5ad(
        _solo_mtx(nc_prefix),
        noncode_out / "matrix.h5ad",
        args.sample_id,
        args.srr,
    )

    prov = {
        "gse": args.gse,
        "srr": args.srr,
        "sample_id": args.sample_id,
        "fetch_meta": meta,
        "gencode_idx": str(args.gencode_idx),
        "noncode_idx": str(args.noncode_idx),
        "finished_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
    }
    (args.out / "provenance.json").write_text(json.dumps(prov, indent=2), encoding="utf-8")
    _prune_star_artifacts(args.out)
    shutil.rmtree(args.work, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e, file=sys.stderr)
        sys.exit(1)
