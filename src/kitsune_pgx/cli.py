from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from kitsune_pgx.config import load_config
from kitsune_pgx.ledger import connect, init_db, reap_stale, reap_stale_fetching, status_counts
from kitsune_pgx.queue_ops import queue_gse, queue_studies_from_manifest
from kitsune_pgx.align_submit import submit_align_job
from kitsune_pgx.ledger import transition
from kitsune_pgx.worker import process_one_sample


def _config_path(p: str | None) -> Path:
    if p:
        return Path(p)
    env = os.environ.get("KITSUNE_CONFIG")
    if env:
        return Path(env)
    for candidate in (
        Path("config.yaml"),
        Path.home() / "kitsune-pgx" / "config.yaml",
        Path("/data/kitsune/config.yaml"),
    ):
        if candidate.is_file():
            return candidate
    sys.exit("No config.yaml found; pass --config or copy config.example.yaml")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="kitsune")
    parser.add_argument("--config", help="Path to config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Ensure ledger schema exists")

    q = sub.add_parser("queue", help="Queue one GSE (fetch runinfo + ledger rows)")
    q.add_argument("gse")
    q.add_argument("--bioproject", required=True)
    q.add_argument("--srp", default="")
    q.add_argument("--tier", default="")
    q.add_argument("--disease", default="")

    qs = sub.add_parser("queue-studies", help="Queue all TO_DOWNLOAD rows from cohort TSV")
    qs.add_argument(
        "--manifest",
        default="manifest/cohort_studies.tsv",
        help="Study-level TSV",
    )
    qs.add_argument(
        "--iridis-runinfo",
        default="/iridisfs/ddnb/Luke/kitsune/download_align_data/results/geo_ai_metadata_tiered",
        help="Reuse existing {GSE}_sra.csv when present",
    )

    sub.add_parser("status", help="Count runs by state")

    r = sub.add_parser("reap", help="Reclaim stale CLAIMED / FETCHING rows")
    r.add_argument("--timeout-min", type=int, default=None)
    r.add_argument(
        "--fetching-timeout-min",
        type=int,
        default=None,
        help="Reset FETCHING idle longer than this (default 720)",
    )

    run_p = sub.add_parser("run", help="Process queue (hybrid worker)")
    run_p.add_argument("--once", action="store_true")
    run_p.add_argument("--dry-run", action="store_true")

    sk = sub.add_parser("skip-gse", help="Mark PENDING runs for a GSE as SKIPPED")
    sk.add_argument("gse")

    rf = sub.add_parser(
        "retry-failed",
        help="Manual only: mark FAILED runs for one retry (not used by worker loop)",
    )
    rf.add_argument("--gse", help="Only retry FAILED rows for this GSE")

    rq = sub.add_parser(
        "requeue-done",
        help="Re-align: reset DONE runs to PENDING (e.g. after fixing GENCODE index)",
    )
    rq.add_argument(
        "--gse",
        action="append",
        required=True,
        help="GSE accession (repeatable)",
    )

    ss = sub.add_parser(
        "submit-staged",
        help="sbatch align on Iridis for a run already in staging (no re-fetch)",
    )
    ss.add_argument("srr")

    sub.add_parser("build-refs", help="Rsync STAR indexes from ddnb into Iridis scratch refs/")

    rep = sub.add_parser(
        "study-report",
        help="Write manifest/study_completion.tsv (per-GSE status for analysis filtering)",
    )
    rep.add_argument(
        "--output",
        help="Output TSV (default: <paths.manifest>/study_completion.tsv)",
    )

    sub.add_parser(
        "prune-scratch",
        help="On Iridis: drop STAR cruft under results/, clear staging/work",
    )
    sub.add_parser(
        "merge-studies",
        help="On Iridis: {GSE}_gencode_merged.h5ad and {GSE}_noncode_merged.h5ad per complete GSE",
    )

    args = parser.parse_args(argv)
    cfg = load_config(_config_path(args.config))

    if args.cmd == "init-db":
        conn = connect(cfg.ledger_path)
        init_db(conn)
        print(f"Ledger ready: {cfg.ledger_path}")
        return

    conn = connect(cfg.ledger_path)

    if args.cmd == "queue":
        total, new = queue_gse(
            conn,
            cfg.manifest_path,
            gse=args.gse,
            bioproject=args.bioproject,
            srp=args.srp,
            disease=args.disease,
            tier=args.tier,
        )
        print(f"{args.gse}: {total} runs in CSV, {new} new ledger rows")
        return

    if args.cmd == "queue-studies":
        summary = queue_studies_from_manifest(
            conn,
            Path(args.manifest),
            cfg.manifest_path,
            skip_tier_x=cfg.skip_tier_x,
            skip_already_processed=cfg.skip_already_processed,
            iridis_runinfo_dir=Path(args.iridis_runinfo),
        )
        for gse, total, new in summary:
            print(f"{gse}: {total} runs, {new} new")
        print(f"Queued {len(summary)} studies")
        return

    if args.cmd == "status":
        from kitsune_pgx.worker import poll_aligning

        n = poll_aligning(cfg)
        if n:
            print(f"(polled {n} ALIGNING row(s))")
        for state, n in status_counts(conn):
            print(f"{state}\t{n}")
        return

    if args.cmd == "reap":
        timeout = args.timeout_min or cfg.raw["limits"]["heartbeat_timeout_min"]
        max_a = cfg.raw["limits"]["max_attempts"]
        n = reap_stale(conn, timeout, max_a)
        ft = args.fetching_timeout_min or cfg.raw["limits"].get(
            "fetching_timeout_min", 720
        )
        nf = reap_stale_fetching(conn, int(ft))
        print(f"Reaped {n} CLAIMED, {nf} FETCHING rows")
        return

    if args.cmd == "run":
        while True:
            did = process_one_sample(cfg, dry_run=args.dry_run)
            if not did:
                print("No PENDING runs")
                break
            if args.once:
                break
        return

    if args.cmd == "submit-staged":
        row = conn.execute("SELECT * FROM runs WHERE srr=?", (args.srr,)).fetchone()
        if not row:
            sys.exit(f"Unknown SRR {args.srr}")
        if row["state"] == "ALIGNING":
            transition(conn, args.srr, "STAGED", from_states=("ALIGNING",))
            row = conn.execute("SELECT * FROM runs WHERE srr=?", (args.srr,)).fetchone()
        if row["state"] not in ("STAGED", "FAILED", "FETCHED"):
            sys.exit(f"Run {args.srr} is {row['state']}; need STAGED/FAILED with staging data")
        gse, sample_id = row["gse"], row["sample_id"]
        staging = cfg.iridis.staging / gse / sample_id
        from kitsune_pgx.sync.iridis import ssh_run

        proc = ssh_run(cfg, f"test -d {staging} && test -f {staging}/fetch_meta.json && echo OK")
        if proc.stdout.strip() != "OK":
            sys.exit(f"Missing staging at {staging}")
        if row["state"] != "STAGED":
            transition(conn, args.srr, "STAGED", from_states=(row["state"],))
        try:
            job_id = submit_align_job(
                cfg, gse=gse, srr=args.srr, sample_id=sample_id
            )
        except Exception as e:
            transition(conn, args.srr, "FAILED", from_states=("STAGED",), detail=str(e)[:2000])
            sys.exit(str(e))
        transition(
            conn,
            args.srr,
            "ALIGNING",
            from_states=("STAGED",),
            slurm_job_id=job_id,
        )
        print(f"Submitted job {job_id} for {args.srr}")
        return

    if args.cmd == "retry-failed":
        if getattr(args, "gse", None):
            cur = conn.execute(
                """
                UPDATE runs SET
                  state='PENDING',
                  last_error=NULL,
                  allow_retry=1
                WHERE state='FAILED' AND gse=?
                """,
                (args.gse,),
            )
        else:
            cur = conn.execute(
                """
                UPDATE runs SET
                  state='PENDING',
                  last_error=NULL,
                  allow_retry=1
                WHERE state='FAILED'
                """
            )
        conn.commit()
        print(f"Reset {cur.rowcount} FAILED rows to PENDING")
        return

    if args.cmd == "requeue-done":
        from kitsune_pgx.sync.iridis import remote_clear_sample_results

        gses = [g.strip() for g in args.gse if g and g.strip()]
        if not gses:
            sys.exit("requeue-done: pass at least one --gse")
        placeholders = ",".join("?" for _ in gses)
        to_clear = conn.execute(
            f"""
            SELECT DISTINCT gse, sample_id FROM runs
            WHERE state='DONE' AND gse IN ({placeholders})
            """,
            gses,
        ).fetchall()
        for row in to_clear:
            remote_clear_sample_results(cfg, row["gse"], row["sample_id"])
        cur = conn.execute(
            f"""
            UPDATE runs SET
              state='PENDING',
              allow_retry=1,
              attempts=0,
              claimed_by=NULL,
              claimed_at=NULL,
              heartbeat_at=NULL,
              slurm_job_id=NULL,
              started_at=NULL,
              synced_at=NULL,
              gencode_h5ad=NULL,
              noncode_h5ad=NULL,
              audit_cram=NULL,
              finished_at=NULL,
              last_error=NULL
            WHERE state='DONE' AND gse IN ({placeholders})
            """,
            gses,
        )
        conn.commit()
        print(
            f"Requeued {cur.rowcount} DONE rows for {', '.join(gses)} "
            f"(cleared {len(to_clear)} sample dirs on Iridis)"
        )
        return

    if args.cmd == "skip-gse":
        cur = conn.execute(
            "UPDATE runs SET state='SKIPPED', last_error='skip-gse' "
            "WHERE gse=? AND state='PENDING'",
            (args.gse,),
        )
        conn.commit()
        print(f"Skipped {cur.rowcount} PENDING rows for {args.gse}")
        return

    if args.cmd == "build-refs":
        script = Path(__file__).resolve().parents[2] / "scripts" / "build_refs.sh"
        subprocess.run(["bash", str(script), str(cfg.iridis.scratch_root)], check=True)
        return

    if args.cmd == "study-report":
        from kitsune_pgx.study_report import write_study_completion_tsv

        out = Path(args.output) if args.output else cfg.manifest_path / "study_completion.tsv"
        n = write_study_completion_tsv(out, conn)
        print(f"Wrote {n} studies to {out}")
        return

    if args.cmd == "prune-scratch":
        from kitsune_pgx.sync.iridis import ssh_run

        root = cfg.iridis.scratch_root
        script = cfg.iridis.repo / "scripts" / "prune_iridis_scratch.sh"
        proc = ssh_run(cfg, f"bash {script} {root}")
        print(proc.stdout or proc.stderr or "prune-scratch finished")
        if proc.returncode != 0:
            sys.exit(proc.returncode or 1)
        return

    if args.cmd == "merge-studies":
        from kitsune_pgx.sync.iridis import ssh_run

        tsv = cfg.manifest_path / "study_completion.tsv"
        if tsv.is_file():
            remote_tsv = cfg.iridis.scratch_root / "manifest" / "study_completion.tsv"
            ssh_run(cfg, f"mkdir -p {remote_tsv.parent}")
            identity = cfg.raw.get("remote", {}).get("identity_file")
            host = cfg.iridis_ssh_host
            from kitsune_pgx.sync.iridis import _remote_user

            user = _remote_user(cfg)
            target = f"{user}@{host}" if "@" not in host else host
            scp = ["scp", "-o", "BatchMode=yes"]
            if identity:
                scp.extend(["-i", str(Path(identity).expanduser())])
            scp.extend([str(tsv), f"{target}:{remote_tsv}"])
            subprocess.run(scp, check=True)
        img = cfg.iridis_refs.apptainer_image
        py = cfg.iridis.repo / "scripts" / "merge_study_h5ad.py"
        remote = (
            f"module load apptainer 2>/dev/null || true; "
            f"apptainer exec -B /iridisfs:/iridisfs {img} "
            f"python {py} --results {cfg.iridis.results} "
            f"--study-tsv {cfg.iridis.scratch_root}/manifest/study_completion.tsv"
        )
        proc = ssh_run(cfg, remote)
        print(proc.stdout or "")
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        if proc.returncode != 0:
            sys.exit(proc.returncode or 1)
        return

    parser.error(f"Unknown command {args.cmd}")


if __name__ == "__main__":
    main()
