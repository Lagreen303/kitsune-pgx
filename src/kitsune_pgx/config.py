from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class IridisPaths:
    scratch_root: Path
    staging: Path
    work: Path
    results: Path
    refs: Path
    logs: Path
    repo: Path


@dataclass(frozen=True)
class IridisRefs:
    gencode_star: Path
    noncode_star: Path
    whitelist_v2: Path
    whitelist_v3: Path
    ref_fa: Path
    apptainer_image: Path


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]
    mode: str
    ledger_path: Path
    work_path: Path
    manifest_path: Path
    logs_path: Path
    iridis_ssh_host: str
    iridis: IridisPaths
    iridis_refs: IridisRefs
    skip_tier_x: bool
    skip_already_processed: bool
    excluded_gse: frozenset[str]
    defer_gse: frozenset[str]
    priority_gse: frozenset[str]
    smallest_gse_first: bool
    verify_md5: bool
    min_free_gb: int
    threads_per_job: int


def load_config(path: Path) -> Config:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    iridis_cfg = data["iridis"]
    root = Path(iridis_cfg["scratch_root"])
    repo = Path(iridis_cfg["repo"]) if iridis_cfg.get("repo") else root / "repo" / "kitsune-pgx"
    ddnb = iridis_cfg.get("ddnb_readonly") or {}
    base = "/iridisfs/ddnb/Luke/kitsune/download_align_data"
    barcodes = f"{base}/cellranger-10.0.0/lib/python/cellranger/barcodes"
    refs = IridisRefs(
        gencode_star=Path(
            ddnb.get(
                "gencode_star",
                f"{base}/reference_sources/STAR_index_gencode49",
            )
        ),
        noncode_star=Path(ddnb.get("noncode_star", f"{base}/NONCODE/STAR_index")),
        whitelist_v2=Path(ddnb.get("whitelist_v2", f"{barcodes}/737K-august-2016.txt")),
        whitelist_v3=Path(
            ddnb.get("whitelist_v3", f"{barcodes}/3M-february-2018_TRU.txt.gz")
        ),
        ref_fa=Path(
            ddnb.get(
                "ref_fa",
                f"{base}/reference_sources/Homo_sapiens.GRCh38.dna.primary_assembly.fa",
            )
        ),
        apptainer_image=Path(
            ddnb.get("apptainer_image", "/iridisfs/ddnb/images/bionemo-framework_nightly")
        ),
    )
    opts = data.get("options", {})
    excl = frozenset(
        g.strip() for g in opts.get("exclude_gse", []) if str(g).strip()
    )
    defer = frozenset(
        g.strip() for g in opts.get("defer_gse", []) if str(g).strip()
    )
    priority = frozenset(
        g.strip() for g in opts.get("priority_gse", []) if str(g).strip()
    )
    limits = data.get("limits", {})
    return Config(
        raw=data,
        mode=data["execution"]["mode"],
        ledger_path=Path(data["paths"]["ledger"]),
        work_path=Path(data["paths"]["work"]),
        manifest_path=Path(data["paths"]["manifest"]),
        logs_path=Path(data["paths"]["logs"]),
        iridis_ssh_host=data["iridis"]["ssh_host"],
        iridis=IridisPaths(
            scratch_root=root,
            staging=root / "staging",
            work=root / "work",
            results=root / "results",
            refs=root / "refs",
            logs=root / "logs",
            repo=repo,
        ),
        skip_tier_x=bool(data.get("options", {}).get("skip_tier_x", True)),
        skip_already_processed=bool(
            data.get("options", {}).get("skip_already_processed", True)
        ),
        iridis_refs=refs,
        excluded_gse=excl,
        defer_gse=defer,
        priority_gse=priority,
        smallest_gse_first=bool(opts.get("smallest_gse_first", True)),
        verify_md5=bool(opts.get("verify_md5", True)),
        min_free_gb=int(limits.get("min_free_gb", 200)),
        threads_per_job=int(limits.get("threads_per_job", 16)),
    )
