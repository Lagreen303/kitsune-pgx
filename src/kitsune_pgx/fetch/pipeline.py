"""ENA-first fetch with SRA fallback when layout/chemistry cannot be resolved."""
from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError

from kitsune_pgx.config import Config
from kitsune_pgx.fetch.chemistry import ChemistryCall, UnsupportedChemistry, classify_fastqs
from kitsune_pgx.fetch.ena import fetch_ena_fastqs
from kitsune_pgx.fetch.fastq_layout import normalize_fastq_dir
from kitsune_pgx.fetch.sra_fallback import fetch_sra_fastqs


def _classify_dir(fastq_dir: Path, srr: str) -> tuple[list[Path], ChemistryCall, int]:
    paths = normalize_fastq_dir(fastq_dir, srr)
    if len(paths) < 2:
        raise ValueError(f"Need at least 2 FASTQs after normalize, got {len(paths)}")
    chem = classify_fastqs(paths)
    nbytes = sum(p.stat().st_size for p in paths)
    return paths, chem, nbytes


def fetch_classified_fastqs(
    cfg: Config,
    srr: str,
    work: Path,
    *,
    heartbeat: Callable[[], None] | None = None,
) -> tuple[list[Path], ChemistryCall, str, int]:
    fastq_dir = work / "fastq"
    fastq_dir.mkdir(parents=True, exist_ok=True)
    ena_err: str | None = None
    stop = threading.Event()

    def _beat_loop() -> None:
        while not stop.wait(600):
            if heartbeat:
                heartbeat()

    beat_thread = threading.Thread(target=_beat_loop, daemon=True)
    beat_thread.start()
    try:
        try:
            fetch_ena_fastqs(srr, fastq_dir, verify_md5=cfg.verify_md5)
            paths, chem, nbytes = _classify_dir(fastq_dir, srr)
            return paths, chem, "ena_fastq", nbytes
        except UnsupportedChemistry:
            raise
        except (FileNotFoundError, ValueError, RuntimeError, HTTPError, URLError, OSError) as e:
            ena_err = str(e)

        shutil.rmtree(fastq_dir, ignore_errors=True)
        fastq_dir.mkdir(parents=True, exist_ok=True)
        try:
            fetch_sra_fastqs(srr, fastq_dir, heartbeat=heartbeat)
            paths, chem, nbytes = _classify_dir(fastq_dir, srr)
            return paths, chem, "sra_fastq", nbytes
        except UnsupportedChemistry:
            raise
        except (FileNotFoundError, ValueError, subprocess.CalledProcessError) as sra_err:
            raise RuntimeError(f"ENA ({ena_err}); SRA ({sra_err})") from sra_err
    finally:
        stop.set()
