"""Submit Iridis SLURM align job for a staged sample."""
from __future__ import annotations

import re
import shlex
import subprocess

from kitsune_pgx.config import Config
from kitsune_pgx.sync.iridis import ssh_run

_JOB_ID_RE = re.compile(r"Submitted batch job (\d+)")


def submit_align_job(cfg: Config, *, gse: str, srr: str, sample_id: str) -> str:
    refs = cfg.iridis_refs
    slurm_script = cfg.iridis.repo / "slurm" / "kitsune_align.sh"
    iridis = cfg.raw.get("iridis", {})
    partition = str(iridis.get("slurm_partition", "amd"))
    mem = str(iridis.get("slurm_mem", "240G"))
    time_limit = str(iridis.get("slurm_time", "12:00:00"))
    export_pairs = [
        ("GSE", gse),
        ("SRR", srr),
        ("SAMPLE_ID", sample_id),
        ("KITSUNE_ROOT", str(cfg.iridis.scratch_root)),
        ("GENCODE_IDX", str(refs.gencode_star)),
        ("NONCODE_IDX", str(refs.noncode_star)),
        ("WL_V2", str(refs.whitelist_v2)),
        ("WL_V3", str(refs.whitelist_v3)),
        ("REF_FA", str(refs.ref_fa)),
        ("APPTAINER_IMG", str(refs.apptainer_image)),
        ("THREADS", str(cfg.threads_per_job)),
    ]
    export_str = "ALL," + ",".join(f"{k}={v}" for k, v in export_pairs)
    log_dir = cfg.iridis.scratch_root / "logs"
    remote = (
        f"cd {shlex.quote(str(cfg.iridis.repo))} && "
        f"mkdir -p {shlex.quote(str(log_dir))} && "
        f"sbatch --partition={shlex.quote(partition)} "
        f"--cpus-per-task={cfg.threads_per_job} "
        f"--mem={shlex.quote(mem)} --time={shlex.quote(time_limit)} "
        f"--output={shlex.quote(str(log_dir / '%x_%j.out'))} "
        f"--error={shlex.quote(str(log_dir / '%x_%j.err'))} "
        f"--export={export_str} "
        f"{shlex.quote(str(slurm_script))}"
    )
    proc = ssh_run(cfg, remote)
    combined = "\n".join(
        x for x in (proc.stdout or "", proc.stderr or "") if x.strip()
    ).strip()
    if proc.returncode != 0:
        raise RuntimeError(
            f"sbatch failed (exit {proc.returncode}): {combined[:2000] or 'no output'}"
        )
    m = _JOB_ID_RE.search(combined)
    if not m:
        raise RuntimeError(f"sbatch output missing job id: {combined[:500]}")
    return m.group(1)
