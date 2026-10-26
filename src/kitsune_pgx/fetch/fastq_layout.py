"""Normalize FASTQ paths after ENA/SRA download."""
from __future__ import annotations

import shutil
from pathlib import Path


def _fastq_base(name: str) -> str:
    if name.endswith(".fastq.gz"):
        return name[:-6]
    if name.endswith(".fastq"):
        return name[:-6]
    return name


def normalize_fastq_dir(dest_dir: Path, srr: str) -> list[Path]:
    """Drop cache dirs, empty files, and duplicate .fastq vs .fastq.gz pairs."""
    cache = dest_dir / "sra_cache"
    if cache.is_dir():
        shutil.rmtree(cache, ignore_errors=True)

    candidates = [
        p
        for p in dest_dir.iterdir()
        if p.is_file()
        and (p.name.endswith(".fastq") or p.name.endswith(".fastq.gz"))
        and p.stat().st_size > 0
    ]
    by_base: dict[str, Path] = {}
    for p in candidates:
        base = _fastq_base(p.name)
        prev = by_base.get(base)
        if prev is None:
            by_base[base] = p
            continue
        # Prefer compressed; remove the other on disk to avoid confusing downstream tools.
        if p.name.endswith(".gz") and not prev.name.endswith(".gz"):
            prev.unlink(missing_ok=True)
            by_base[base] = p
        elif prev.name.endswith(".gz") and not p.name.endswith(".gz"):
            p.unlink(missing_ok=True)
        else:
            by_base[base] = p

    paths = sorted(by_base.values(), key=lambda x: x.name)
    has_mates = any("_1." in p.name for p in paths) and any("_2." in p.name for p in paths)
    if has_mates:
        drop = {f"{srr}.fastq", f"{srr}.fastq.gz"}
        paths = [p for p in paths if p.name not in drop]
    return paths
