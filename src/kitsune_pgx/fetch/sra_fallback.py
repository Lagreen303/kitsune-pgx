"""SRA prefetch + fasterq-dump when ENA has no FASTQ."""
from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run_with_heartbeat(
    cmd: list[str],
    *,
    heartbeat: Callable[[], None] | None = None,
    pulse_sec: int = 300,
) -> None:
    proc = subprocess.Popen(cmd)
    while proc.poll() is None:
        time.sleep(pulse_sec)
        if heartbeat:
            heartbeat()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode or 1, cmd)


def fetch_sra_fastqs(
    srr: str,
    dest_dir: Path,
    *,
    heartbeat: Callable[[], None] | None = None,
) -> tuple[list[Path], int]:
    prefetch = _which("prefetch")
    fasterq = _which("fasterq-dump")
    if not prefetch or not fasterq:
        raise FileNotFoundError("prefetch/fasterq-dump not on PATH (install sra-toolkit on PGX)")
    dest_dir.mkdir(parents=True, exist_ok=True)
    sra_dir = dest_dir / "sra_cache"
    sra_dir.mkdir(parents=True, exist_ok=True)
    _run_with_heartbeat(
        [prefetch, srr, "-O", str(sra_dir), "--max-size", "500G"],
        heartbeat=heartbeat,
    )
    _run_with_heartbeat(
        [
            fasterq,
            srr,
            "--split-files",
            "--include-technical",
            "-O",
            str(dest_dir),
            "-e",
            str(sra_dir),
        ],
        heartbeat=heartbeat,
    )
    from kitsune_pgx.fetch.fastq_layout import normalize_fastq_dir

    fastqs = normalize_fastq_dir(dest_dir, srr)
    if not fastqs:
        raise FileNotFoundError(f"fasterq-dump produced no FASTQs for {srr}")
    total = sum(p.stat().st_size for p in fastqs)
    return fastqs, total
