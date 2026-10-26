from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from kitsune_pgx.config import Config
from kitsune_pgx.fetch.chemistry import ChemistryCall
from kitsune_pgx.fetch.chemistry import UnsupportedChemistry
from kitsune_pgx.fetch.pipeline import fetch_classified_fastqs
from kitsune_pgx.ledger import claim_next, connect, heartbeat, heartbeat_path, transition
from kitsune_pgx.align_submit import submit_align_job
from kitsune_pgx.sync.iridis import remote_provenance_ok, rsync_to_staging, slurm_job_state, ssh_run


def _disk_free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / (1024**3)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def poll_aligning(cfg: Config) -> int:
    conn = connect(cfg.ledger_path)
    rows = conn.execute(
        "SELECT srr, gse, sample_id, slurm_job_id, started_at "
        "FROM runs WHERE state = 'ALIGNING'"
    ).fetchall()
    n = 0
    for row in rows:
        srr = row["srr"]
        gse = row["gse"]
        sample_id = row["sample_id"]
        job_id = row["slurm_job_id"]
        started_at = row["started_at"]
        if remote_provenance_ok(cfg, gse, sample_id, align_started_at=started_at):
            transition(
                conn,
                srr,
                "DONE",
                from_states=("ALIGNING",),
                finished_at=_now(),
                gencode_h5ad=str(
                    cfg.iridis.results / gse / sample_id / "gencode" / "matrix.h5ad"
                ),
                noncode_h5ad=str(
                    cfg.iridis.results / gse / sample_id / "noncode" / "matrix.h5ad"
                ),
            )
            ssh_run(
                cfg,
                f"rm -rf {cfg.iridis.staging / gse / sample_id} {cfg.iridis.work / sample_id}",
            )
            n += 1
            continue
        state = slurm_job_state(cfg, job_id or "")
        if state == "COMPLETED":
            transition(
                conn,
                srr,
                "FAILED",
                from_states=("ALIGNING",),
                detail=f"SLURM job {job_id} COMPLETED but no provenance.json",
            )
            n += 1
            continue
        if state in ("FAILED", "CANCELLED", "TIMEOUT", "NODE_FAIL", "OUT_OF_MEMORY"):
            transition(
                conn,
                srr,
                "FAILED",
                from_states=("ALIGNING",),
                detail=f"SLURM job {job_id} state={state}",
            )
            n += 1
            continue
        if state == "UNKNOWN" and not job_id:
            transition(
                conn,
                srr,
                "FAILED",
                from_states=("ALIGNING",),
                detail="ALIGNING with no slurm_job_id",
            )
            n += 1
    conn.close()
    return n


def _write_fetch_meta(work: Path, chem: ChemistryCall, source: str, nbytes: int) -> None:
    meta = {
        "source": source,
        "fastq_bytes": nbytes,
        "chemistry": chem.chemistry,
        "cb_len": chem.cb_len,
        "umi_len": chem.umi_len,
        "r1_len": chem.r1_len,
        "r2_len": chem.r2_len,
        "r1": chem.r1_path.name,
        "r2": chem.r2_path.name,
    }
    (work / "fetch_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def process_one_sample(cfg: Config, dry_run: bool = False) -> bool:
    poll_aligning(cfg)

    conn = connect(cfg.ledger_path)
    row = claim_next(
        conn,
        smallest_gse_first=cfg.smallest_gse_first,
        defer_gse=cfg.defer_gse,
        priority_gse=cfg.priority_gse,
    )
    if not row:
        conn.close()
        return False

    srr = row["srr"]
    gse = row["gse"]
    sample_id = row["sample_id"]
    work = cfg.work_path / srr

    try:
        if gse in cfg.excluded_gse:
            transition(conn, srr, "SKIPPED", from_states=("CLAIMED",), detail="exclude_gse policy")
            return True

        if _disk_free_gb(cfg.work_path) < cfg.min_free_gb:
            transition(conn, srr, "PENDING", from_states=("CLAIMED",), detail="low disk; release claim")
            return True

        transition(conn, srr, "FETCHING", from_states=("CLAIMED",))
        heartbeat(conn, srr)

        if dry_run:
            transition(conn, srr, "PENDING", detail="dry-run reset")
            return True

        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)

        paths, chem, source, nbytes = fetch_classified_fastqs(
            cfg,
            srr,
            work,
            heartbeat=lambda: heartbeat_path(cfg.ledger_path, srr),
        )
        _write_fetch_meta(work, chem, source, nbytes)

        transition(
            conn,
            srr,
            "FETCHED",
            from_states=("FETCHING",),
            source=source,
            fastq_bytes=nbytes,
            chemistry=chem.chemistry,
            cb_len=chem.cb_len,
            umi_len=chem.umi_len,
            r1_len=chem.r1_len,
            r2_len=chem.r2_len,
        )

        rsync_to_staging(cfg, work, gse, sample_id)
        transition(conn, srr, "STAGED", from_states=("FETCHED",))

        try:
            job_id = submit_align_job(cfg, gse=gse, srr=srr, sample_id=sample_id)
        except Exception as e:
            transition(
                conn,
                srr,
                "FAILED",
                from_states=("STAGED",),
                detail=str(e)[:2000],
            )
            return True
        transition(
            conn,
            srr,
            "ALIGNING",
            from_states=("STAGED",),
            slurm_job_id=job_id,
            started_at=_now(),
        )

        shutil.rmtree(work, ignore_errors=True)
        return True
    except UnsupportedChemistry as e:
        transition(
            conn,
            srr,
            "SKIPPED",
            from_states=("CLAIMED", "FETCHING"),
            detail=str(e)[:2000],
        )
        shutil.rmtree(work, ignore_errors=True)
        return True
    except Exception as e:
        msg = str(e).strip() or repr(e)
        try:
            transition(conn, srr, "FAILED", detail=msg[:2000])
        except Exception:
            conn.execute(
                "UPDATE runs SET state='FAILED', last_error=? WHERE srr=?",
                (msg[:2000], srr),
            )
            conn.commit()
        shutil.rmtree(work, ignore_errors=True)
        return True
    finally:
        conn.close()
