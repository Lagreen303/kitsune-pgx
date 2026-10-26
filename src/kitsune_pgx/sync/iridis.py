from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from kitsune_pgx.config import Config
from kitsune_pgx.sync.provenance import provenance_from_json, provenance_valid_for_align


def _remote_user(cfg: Config) -> str:
    user = cfg.raw.get("remote", {}).get("user")
    if user:
        return str(user)
    return os.environ.get("USER") or os.environ.get("USERNAME") or ""


def _ssh_base(cfg: Config) -> list[str]:
    user = _remote_user(cfg)
    host = cfg.iridis_ssh_host
    target = f"{user}@{host}" if "@" not in host else host
    identity = cfg.raw.get("remote", {}).get("identity_file")
    cmd = ["ssh", "-o", "BatchMode=yes"]
    if identity:
        cmd.extend(["-i", str(Path(identity).expanduser())])
    cmd.append(target)
    return cmd


def ssh_run(cfg: Config, remote_cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _ssh_base(cfg) + [remote_cmd],
        capture_output=True,
        text=True,
        check=False,
    )


def rsync_to_staging(
    cfg: Config,
    local_dir: Path,
    gse: str,
    sample_id: str,
) -> Path:
    remote_root = cfg.iridis.staging / gse / sample_id
    ssh_run(cfg, f"mkdir -p {remote_root}")
    user = _remote_user(cfg)
    host = cfg.iridis_ssh_host
    target = f"{user}@{host}" if "@" not in host else host
    remote = f"{target}:{remote_root}/"
    identity = cfg.raw.get("remote", {}).get("identity_file")
    ssh_cmd = "ssh -o BatchMode=yes"
    if identity:
        ssh_cmd += f" -i {Path(identity).expanduser()}"
    cmd = [
        "rsync",
        "-av",
        "--partial",
        "--timeout=600",
        "-e",
        ssh_cmd,
        f"{local_dir}/",
        remote,
    ]
    last: subprocess.CalledProcessError | None = None
    for attempt in range(3):
        try:
            subprocess.run(cmd, check=True)
            return remote_root
        except subprocess.CalledProcessError as e:
            last = e
            if attempt < 2:
                time.sleep(45 * (attempt + 1))
    raise RuntimeError(
        f"rsync to {remote_root} failed after 3 attempts (exit {last.returncode if last else '?'})"
    ) from last


def slurm_job_state(cfg: Config, job_id: str) -> str:
    if not job_id:
        return "UNKNOWN"
    proc = ssh_run(cfg, f"sacct -j {job_id} -n -X -o State 2>/dev/null | head -1")
    raw = (proc.stdout or "").strip()
    if not raw:
        return "UNKNOWN"
    # sacct may return "CANCELLED+", "CANCELLED by 0", "COMPLETED", etc.
    token = raw.split()[0].rstrip("+")
    return token


def remote_clear_sample_results(cfg: Config, gse: str, sample_id: str) -> None:
    """Drop Iridis outputs so a re-align cannot satisfy poll via stale provenance."""
    base = cfg.iridis.results / gse / sample_id
    staging = cfg.iridis.staging / gse / sample_id
    work = cfg.iridis.work / sample_id
    ssh_run(
        cfg,
        f"rm -rf {base} {staging} {work}",
    )


def remote_provenance_ok(
    cfg: Config,
    gse: str,
    sample_id: str,
    *,
    align_started_at: str | None,
) -> bool:
    if not align_started_at:
        return False
    p = cfg.iridis.results / gse / sample_id / "provenance.json"
    proc = ssh_run(cfg, f"cat {p} 2>/dev/null")
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return False
    prov = provenance_from_json(proc.stdout)
    if not prov:
        return False
    return provenance_valid_for_align(
        prov,
        align_started_at=align_started_at,
        expected_gencode_idx=str(cfg.iridis_refs.gencode_star),
    )
