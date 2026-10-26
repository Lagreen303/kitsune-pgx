# kitsune-pgx

Hybrid scRNA acquisition: **PGX** fetches and queues; **Iridis SLURM** aligns. Iridis pipeline writes go under `iridis.scratch_root` in your config (typically `/iridisfs/scratch/<user>/kitsune/`, not ddnb).

## Quick start

```bash
cp config.example.yaml config.yaml   # edit paths for pgx vs iridis login
pip install -e ".[dev]"

kitsune init-db
kitsune queue GSE120221 --bioproject PRJNA492227 --tier 0
kitsune queue-studies --manifest manifest/cohort_studies.tsv
kitsune status
kitsune run --once
```

## SSH

Configure `Host` aliases in `~/.ssh/config` (e.g. `pgx` for the fetch workstation, `iridis` for the cluster login node). Set `remote.user` and `iridis.ssh_host` in `config.yaml` — do not commit real hostnames or usernames.

## Layout

| Host | Path |
|------|------|
| PGX (fetch host) | `~/kitsune/{ledger,manifest,work,logs}` and repo `~/kitsune-pgx` |
| Iridis scratch | `$scratch_root/{refs,staging,work,results,repo,logs}` (see `config.example.yaml`) |

On PGX use the full path (or add `export PATH="$HOME/kitsune-pgx/bin:$PATH"` to `~/.bashrc`):

```bash
~/kitsune-pgx/bin/kitsune status
~/kitsune-pgx/bin/kitsune queue-studies --manifest manifest/cohort_studies.tsv
~/kitsune-pgx/bin/kitsune run --once    # one sample: ENA fetch → rsync → Iridis sbatch
```

### How FASTQ download is automated (ENA → SRA)

Nothing is started manually per SRR. The **PGX worker** (`kitsune run --once`, usually in a tmux loop) drives fetch, staging, and Iridis alignment from the SQLite ledger.

**1. Queue runs (NCBI SRA metadata, not hand-built SRR lists)**

- `kitsune queue GSE… --bioproject PRJNA…` or `kitsune queue-studies --manifest manifest/cohort_studies.tsv`
- For each GSE, `fetch/runinfo.py` calls NCBI **esearch** + **efetch** (`rettype=runinfo`) on the BioProject and writes `manifest/runinfo/{GSE}_sra.csv` with columns `srr,gse,sample_id`.
- One ledger row per SRR is inserted (`PENDING`).

**2. Claim and fetch (per sample)**

`worker.process_one_sample` → `fetch/pipeline.fetch_classified_fastqs`:

| Step | What happens | Code |
|------|----------------|------|
| ENA primary | ENA filereport API (`fastq_ftp` / MD5 / bytes); **wget** each `.fastq.gz`; optional MD5 verify (`verify_md5` in config). Retries 5xx/429 on the API. | `fetch/ena.py` |
| Normalize + chemistry | Rename/sort FASTQs under `work/{SRR}/fastq/`; infer 10x v2/v3 (including SRA 3-file technical layout) from read lengths. | `fetch/fastq_layout.py`, `fetch/chemistry.py` |
| SRA fallback | If ENA is empty, MD5 fails, wget fails, or layout/chemistry fails (except unsupported chemistry → `SKIPPED`), wipe `fastq/` and run **NCBI SRA Toolkit** on PGX: `prefetch -O …/sra_cache --max-size 500G`, then `fasterq-dump --split-files --include-technical -e sra_cache`. | `fetch/sra_fallback.py` |
| Record source | Ledger `source` is `ena_fastq` or `sra_fastq`; `fetch_meta.json` is written before rsync. | `worker.py`, `fetch/pipeline.py` |

**PGX requirements for SRA:** `prefetch` and `fasterq-dump` on `PATH` (same SRA Toolkit install as the old ThinkStation prefetch workflow). Long downloads call the ledger **heartbeat** every 5 minutes so `reap-stale` does not reset `FETCHING` mid-prefetch (`fetching_timeout_min`, default 720).

**3. After fetch**

- Rsync `work/{SRR}/` → Iridis `staging/{GSE}/{sample_id}/` (includes FASTQs + `fetch_meta.json`).
- `sbatch` dual STARsolo align on Iridis; poll until `provenance.json` → `DONE`; delete staging/work on Iridis.

**Operational commands**

```bash
kitsune run --once                    # one ledger row end-to-end
kitsune run --reap --fetching-timeout-min 720   # return stuck FETCHING → PENDING
kitsune retry-failed --gse GSE279904  # after fixing ENA/SRA issues
```

GSE120221 and other defer-listed studies often hit **SRA** because ENA has no FASTQ or MD5 mismatch. Priority cohort re-aligns are controlled via `priority_gse` in `config.pgx.example.yaml` (copy to `config.pgx.yaml` on PGX).

### NONCODE v7 bulk downloads (Iridis scratch, separate from the worker)

Pre-aligned Cell Ranger bundles from [NONCODE v7](https://v7.noncode.org) are **not** part of the ledger worker. Use login-node Python 3.11+ and Iridis scratch:

```bash
python3.11 scripts/noncode_v7_download.py --cohort pbmc-healthy-and-hema --write-manifest
python3.11 scripts/noncode_v7_download.py \
  --download-manifest manifest/noncode_v7_pbmc_hema.tsv \
  --out /iridisfs/scratch/YOUR_USER/noncode_v7
```

(v7.noncode.org currently has an expired TLS cert — the script uses `curl -k`.)

### Queue order

With `smallest_gse_first: true` (default in `config.pgx.yaml`), the worker claims runs from **smallest GSEs first** (fewest SRR rows per study), then larger ones. `defer_gse` pushes megastudies (e.g. GSE144568, GSE227903) to the **end**.

**Queue:** you do **not** need to cancel PENDING rows. `run` consumes them one at a time. Use `skip-gse GSE169426` (already applied) for on-hold studies.

**Worker loop (tmux on PGX):** `while true; do ~/kitsune-pgx/bin/kitsune run --once; sleep 30; done`

Interactive bash only: `. ~/kitsune-pgx/scripts/pgx-env.sh` then `kitsune` (do not run `source` in PowerShell).

Use `~/kitsune` on the fetch host unless your site provides a shared `/data/kitsune` path.

See `docs/SPEC.md` (from `kitsune_pgx_spec.md`) for full behaviour.
