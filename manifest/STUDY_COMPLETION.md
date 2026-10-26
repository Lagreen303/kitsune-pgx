# Study completion tracking

Per-**GSE** summary derived from the SQLite ledger (`runs` table). One row per study, not per SRR.

## Files

| File | Role |
|------|------|
| **`study_completion.tsv`** | Auto-generated. Regenerate often; do not hand-edit. |
| **`study_analysis_notes.tsv`** | Optional manual notes / overrides (safe to edit). |

## Regenerate

On PGX (or anywhere with the ledger):

```bash
~/kitsune-pgx/bin/kitsune study-report
```

Writes `~/kitsune/manifest/study_completion.tsv` by default (`paths.manifest` in `config.pgx.yaml`).

Optional path:

```bash
kitsune study-report --output /path/to/study_completion.tsv
```

The worker loop refreshes this each cycle (`scripts/pgx-worker-loop.sh`).

## Merged AnnData (complete studies only)

After `study-report` shows `analysis_ready=Y`, on PGX:

```bash
~/kitsune-pgx/bin/kitsune merge-studies
```

Writes **two** objects per GSE under Iridis `results/<GSE>/`:

- `{GSE}_gencode_merged.h5ad`
- `{GSE}_noncode_merged.h5ad`

Do not combine gencode and noncode into a single matrix; keep layers separate for analysis.

## Queue / retries

The worker only claims **`PENDING` runs with `attempts=0`**, or rows explicitly marked via **`kitsune retry-failed`** (`allow_retry=1`). Failed fetch/chemistry rows stay **`FAILED`** until you fix the pipeline and run **`retry-failed` manually** — the worker loop does **not** call it.

## Columns (`study_completion.tsv`)

| Column | Meaning |
|--------|---------|
| `gse` | GEO study accession |
| `total_runs` | Rows in ledger for this GSE |
| `done` / `failed` / `skipped` / `pending` / `in_flight` | Run counts by state |
| `study_status` | `complete`, `failed_all`, `in_progress`, `partial`, `skipped_all`, `other` |
| `analysis_ready` | **`Y`** only if every **non-skipped** run is **DONE** (no failed / pending / in-flight) |
| `top_failure_summary` | Most common `last_error` among FAILED runs in that GSE |
| `generated_at_utc` | When the report was built |

Failures are tracked per **SRR** in the ledger; `study_status` rolls them up so you can filter to **complete studies** for analysis.

## Analysis filtering examples

**Complete studies only (auto rule):**

```bash
awk -F'\t' 'NR==1 || ($9=="Y")' study_completion.tsv
```

**Exclude known-bad cohorts (manual):** join or filter on `study_analysis_notes.tsv` (`include_in_analysis` = `no`).

## `study_status` values

- **`complete`** — all active runs DONE (skipped runs ignored).
- **`failed_all`** — every active run FAILED; nothing left pending (systematic fetch/chemistry issue until fixed).
- **`in_progress`** — still PENDING or FETCHING / ALIGNING / etc.
- **`partial`** — mix of DONE and FAILED with nothing still queued (needs retry or per-run decision).
- **`skipped_all`** — entire GSE skipped (e.g. policy).

## GENCODE layer: index incident (2026-10)

Runs aligned before the default index fix used `reference_sources/STAR_index` on ddnb (~**54** genes in `geneInfo.tab`, cellranger-tiny scale). The intended GENCODE v49 index is **`STAR_index_gencode49`** (~78k genes). NONCODE outputs were unaffected.

**Symptoms:** `{sample}/gencode/matrix.h5ad` and `{GSE}_gencode_merged.h5ad` have ~54 features (Y_RNA, U6, rRNA-like names); `noncode/` matrices remain ~95k genes.

**Fix (pipeline):** `gencode_star` / `GENCODE_IDX` now point at `STAR_index_gencode49` (see `config.pgx.yaml` `iridis.ddnb_readonly`).

**Re-quantify gencode:** `kitsune requeue-done --gse GSE…` resets ledger rows, **deletes each sample’s Iridis results/staging/work**, then re-fetch + align. `poll_aligning` only accepts `provenance.json` with `finished_at` **after** the row’s `started_at` and `gencode_idx` matching config (stale tiny-index provenance is ignored). Re-run `merge-studies` after studies are complete again; check gencode `n_vars` ~ tens of thousands.
