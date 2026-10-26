#!/usr/bin/env python3
import shlex
import traceback
from pathlib import Path

import yaml

from kitsune_pgx.config import load_config
from kitsune_pgx.align_submit import submit_align_job

cfg = load_config(Path("/home/lag1e24/kitsune-pgx/config.pgx.yaml"))
ir = cfg.raw["iridis"]
print("slurm_time type", type(ir["slurm_time"]), repr(ir["slurm_time"]))
print("slurm_mem type", type(ir["slurm_mem"]), repr(ir["slurm_mem"]))
try:
    shlex.quote(ir["slurm_time"])
    print("shlex time OK")
except Exception as e:
    print("shlex time FAIL", e)

try:
    job_id = submit_align_job(
        cfg, gse="GSE183326", srr="SRR15707781", sample_id="GSM5555661_SRR15707781"
    )
    print("job_id", job_id)
except Exception:
    traceback.print_exc()
