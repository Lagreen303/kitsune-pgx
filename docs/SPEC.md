# kitsune-pgx — implementation spec

Build spec for the PGX-side acquisition and quantification pipeline. Hand this to Cursor as the source of truth.

**Goal.** For every run in a cohort manifest of public 10x scRNA studies: fetch reads, quantify against **two** annotations (GENCODE v49 and NONCODE v6) on the same genome, emit h5ad plus provenance plus a small locus CRAM, sync results to iridis, and delete all local scratch — one sample at a time, resumable, auditable, unattended.

**Hardware.** PGX: ~1.8 TB local storage, internet access, runs the whole pipeline. iridis: receives results only; the discovery analysis runs there separately.

---

## 0. Constraints that drive the design

| Constraint | Consequence |
|---|---|
| 1.8 TB local, cohort is 4–8 TB | Nothing accumulates. Per-sample scratch is created, used, deleted. |
| Runs unattended for weeks | Every step idempotent; crash at any point must be safely resumable with no manual cleanup. |
| Two annotations required | Two STARsolo passes per sample against two prebuilt indexes on one genome. |
| Cohort spans years of 10x chemistry | Chemistry detected per run, never assumed. A wrong preset produces plausible wrong output silently. |
| Previous project could not audit mapping | A locus CRAM is retained for every sample, permanently. |
| Feature space must be identical everywhere | One pinned reference, checksummed, recorded per sample. |

---

## 1. Directory layout

```
/data/kitsune/                      # PGX, persistent
  refs/
    GRCh38.primary.fa               # pinned, checksummed
    gencode.v49.annotation.gtf
    noncode.v6.hg38.gtf
    star_index_gencode_v49/
    star_index_noncode_v6/
    whitelists/
      737K-august-2016.txt          # 10x v2
      3M-february-2018.txt          # 10x v3 / v3.1
    audit_regions.bed               # loci retained in CRAM (see §7)
    REFERENCE_MANIFEST.json         # paths + sha256 + versions
  ledger/
    kitsune.db                      # SQLite, WAL mode
    kitsune.db.bak.<date>           # nightly copy
  manifest/
    cohort.tsv                      # input: gse, srp, srr, sample_id, donor_id, disease, tier
  results/<gse>/<sample_id>/        # persistent, small; rsynced to iridis
    gencode/{matrix.h5ad,Summary.csv,Log.final.out,Barcodes.stats,Features.stats}
    noncode/{matrix.h5ad,Summary.csv,Log.final.out,Barcodes.stats,Features.stats}
    audit/<sample_id>.loci.cram{,.crai}
    provenance.json
  logs/<gse>/<sample_id>.log

/scratch/kitsune/work/<sample_id>/  # PGX, ephemeral — DELETED after every sample
  fastq/ bam/ star_tmp/
```

`/scratch/kitsune` should be on the fastest local disk available. `star_tmp` must be local, never network.

---

## 2. Ledger schema (SQLite, WAL)

The ledger is the pipeline's only state. File existence is never used to infer progress.

```sql
CREATE TABLE runs (
  srr             TEXT PRIMARY KEY,
  gse             TEXT NOT NULL,
  srp             TEXT NOT NULL,
  sample_id       TEXT NOT NULL,       -- grouping key; may span several SRRs
  donor_id        TEXT,
  disease         TEXT,
  tier            TEXT,

  state           TEXT NOT NULL DEFAULT 'PENDING',
  claimed_by      TEXT,                -- hostname:pid
  claimed_at      TIMESTAMP,
  heartbeat_at    TIMESTAMP,
  attempts        INTEGER NOT NULL DEFAULT 0,
  last_error      TEXT,

  chemistry       TEXT,                -- v2 | v3 | unknown
  cb_len          INTEGER,
  umi_len         INTEGER,
  r1_len          INTEGER,
  r2_len          INTEGER,
  source          TEXT,                -- ena_fastq | sra_bam | sra_fastq
  fastq_bytes     INTEGER,
  read_count      INTEGER,

  ref_manifest_sha TEXT,               -- ties output to an exact reference
  gencode_h5ad    TEXT,
  noncode_h5ad    TEXT,
  audit_cram      TEXT,
  synced_at       TIMESTAMP,

  started_at      TIMESTAMP,
  finished_at     TIMESTAMP
);
CREATE INDEX idx_state ON runs(state);
CREATE INDEX idx_sample ON runs(sample_id);

CREATE TABLE events (              -- append-only audit trail
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  srr TEXT, ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  from_state TEXT, to_state TEXT, detail TEXT
);
```

**States:** `PENDING → CLAIMED → FETCHING → FETCHED → ALIGNING → ALIGNED → SYNCING → DONE`, plus `FAILED`, `SKIPPED`, `QUARANTINE`.

**Claiming must be atomic:**
```sql
UPDATE runs SET state='CLAIMED', claimed_by=?, claimed_at=CURRENT_TIMESTAMP, attempts=attempts+1
WHERE srr = (SELECT srr FROM runs WHERE state='PENDING' ORDER BY tier, gse, srr LIMIT 1)
RETURNING srr;
```
A worker writes `heartbeat_at` every 60 s. A reaper returns any row whose heartbeat is older than 30 minutes to `PENDING` (or to `QUARANTINE` after `attempts >= 3`).

---

## 3. Per-sample flow

Each step is a function; each transition is a ledger write. Any step may be re-entered from the start of its state.

1. **Claim** a run (or a sample's full set of runs — see §11).
2. **Pre-flight**: free space on `/scratch/kitsune` ≥ `min_free_gb` (config, default 200). If not, release the claim and sleep.
3. **Fetch** (§4) → records `source`, `fastq_bytes`, md5s verified.
4. **Detect chemistry** (§5) → records `chemistry`, `cb_len`, `umi_len`, `r1_len`, `r2_len`. Unknown ⇒ `SKIPPED`, never guessed.
5. **STARsolo GENCODE pass** (§6), with sorted BAM output.
6. **Extract locus CRAM** (§7) from that BAM, then delete the BAM.
7. **STARsolo NONCODE pass** (§6), no BAM output.
8. **Convert both matrices to h5ad** (§8), write `provenance.json`.
9. **Sync** results to iridis (§9).
10. **Delete** `/scratch/kitsune/work/<sample_id>` in full. Mark `DONE`.

Cleanup runs in a `finally` block — a failure must not leave scratch behind.

---

## 4. Fetch

**Primary: ENA.** Per run:

```
https://www.ebi.ac.uk/ena/portal/api/filereport
  ?accession=<SRR>&result=read_run
  &fields=run_accession,fastq_ftp,fastq_md5,fastq_bytes,read_count,submitted_ftp,submitted_format
  &format=tsv
```

`fastq_ftp` is `;`-separated. Prefix each with `https://` and download. **Verify md5 against `fastq_md5`** — a corrupt FASTQ that aligns badly is worse than a failed download.

**Fallbacks, in order:**
- `fastq_ftp` empty but `submitted_ftp` shows a BAM → 10x-submitted BAM. Download and convert with `bamtofastq` (10x). Record `source='sra_bam'`.
- ENA returns nothing → try SRA (`prefetch` + `fasterq-dump --split-files --include-technical`), record `source='sra_fastq'`. If that also fails, `state='FAILED'` with the error.

**Never leave `.sra` or intermediate FASTQ outside the sample scratch dir.**

### 4.1 Identifying which file is which

This is the step most likely to be silently wrong. Do **not** rely on `_1`/`_2`/`_3` filename ordering — SRA submissions vary. Identify by read length, measured from the first record of each file:

| Observed length | Role |
|---|---|
| 8 (or 10) bp | I1/I2 sample index — discard |
| 26 bp | R1, 10x **v2** (CB 16 + UMI 10) |
| 28 bp | R1, 10x **v3/v3.1** (CB 16 + UMI 12) |
| ≥ 50 bp | R2, cDNA |

If exactly one file matches an R1 pattern and one matches R2, proceed. Otherwise `SKIPPED` with the observed lengths in `last_error`. Ambiguity is never resolved by guessing.

---

## 5. Chemistry

Derived from the R1 length above:

| R1 len | chemistry | cb_len | umi_len | whitelist |
|---|---|---|---|---|
| 26 | v2 | 16 | 10 | `737K-august-2016.txt` |
| 28 | v3 | 16 | 12 | `3M-february-2018.txt` |

Optional confirmation, cheap and worth it: take 100k reads, compute the fraction of barcodes matching each whitelist, and require the chosen whitelist to win by a wide margin. Record both rates. If the margin is small, `SKIPPED`.

Note 10x v4/GEM-X uses a different whitelist again. If any run's R1 is neither 26 nor 28 bp, do not extend the table by guessing — fail loudly and add the case deliberately.

---

## 6. STARsolo

Two passes, identical except the index and BAM output. **Read order is cDNA first, then barcode read** — this is a common and silent error.

```bash
STAR \
  --genomeDir        ${IDX}                     \
  --readFilesIn      ${R2_cDNA} ${R1_CB}        \
  --readFilesCommand zcat                       \
  --soloType         CB_UMI_Simple              \
  --soloCBwhitelist  ${WHITELIST}               \
  --soloCBlen        16                         \
  --soloUMIlen       ${UMI_LEN}                 \
  --soloBarcodeReadLength 0                     \
  --soloCBmatchWLtype 1MM_multi_Nbase_pseudocounts \
  --soloUMIdedup     1MM_CR                     \
  --soloUMIfiltering MultiGeneUMI_CR            \
  --soloFeatures     GeneFull                   \
  --soloCellFilter   EmptyDrops_CR              \
  --outTmpDir        /scratch/kitsune/work/${SID}/star_tmp \
  --outFileNamePrefix ${OUT}/                   \
  --runThreadN       ${THREADS}                 \
  ${BAM_ARGS}
```

- GENCODE pass: `BAM_ARGS="--outSAMtype BAM SortedByCoordinate --outSAMattributes NH HI AS nM CB UB"`
- NONCODE pass: `BAM_ARGS="--outSAMtype None"`

Only the GENCODE pass emits BAM. Alignments are identical between passes (same genome); only feature assignment differs, so one BAM serves the audit for both.

**Do not set `--soloMultiMappers`** unless deliberately changing behaviour — record the STAR default in `provenance.json` so the choice is explicit rather than implicit. Record `--outFilterMultimapNmax` likewise.

**Memory.** Each human index with annotation needs roughly 32–40 GB resident. Two indexes concurrently need ~70–80 GB. Determine PGX RAM before setting concurrency (§11); if RAM is tight, run passes strictly sequentially, which the flow above already does.

---

## 7. Locus CRAM

After the GENCODE pass:

```bash
samtools index ${BAM}
samtools view -C -T ${REF_FA} -L ${AUDIT_BED} -o ${OUT}/audit/${SID}.loci.cram ${BAM}
samtools index ${OUT}/audit/${SID}.loci.cram
rm -f ${BAM} ${BAM}.bai
```

`audit_regions.bed` must be defined **generously at the start** — adding regions later means realigning everything. Include at minimum:

- every candidate lncRNA locus under consideration, plus flanks
- their paralogues and the surrounding duplicated regions
- acrocentric short-arm regions (chr13/14/15/21/22 p-arms)
- known pseudogene-rich regions (e.g. the PMS2/PMS2P cluster)
- a set of ordinary control loci for comparison
- chrX loci relevant to sex inference (XIST and the Y-linked panel)

Make it configurable, but treat changes as a reason to version the output tree.

---

## 8. Outputs and provenance

Convert both `GeneFull/filtered` matrices to h5ad. Write `provenance.json` per sample containing, at minimum:

```json
{
  "sample_id": "...", "srrs": ["..."], "gse": "...", "donor_id": "...",
  "source": "ena_fastq", "fastq_md5_verified": true,
  "chemistry": "v3", "cb_len": 16, "umi_len": 12, "r1_len": 28, "r2_len": 91,
  "whitelist_sha256": "...", "whitelist_match_rate": {"v2": 0.02, "v3": 0.94},
  "reference": {"manifest_sha256": "...", "genome": "GRCh38.primary",
                "gencode": "v49", "noncode": "v6"},
  "star_version": "...", "star_cmd_gencode": "...", "star_cmd_noncode": "...",
  "samtools_version": "...", "pipeline_git_sha": "...",
  "n_cells_gencode": 0, "n_cells_noncode": 0,
  "started_at": "...", "finished_at": "...", "host": "pgx"
}
```

`pipeline_git_sha` is mandatory — results must be traceable to the code that made them.

---

## 9. Sync to iridis

After outputs are written and before scratch is deleted:

```bash
rsync -avz --partial --checksum \
  /data/kitsune/results/<gse>/<sample_id>/ \
  <user>@iridis:/scratch/<user>/kitsune/results/<gse>/<sample_id>/
```

Record `synced_at` only on a zero exit code. If sync fails, keep the local results (they are small) and retry on a later pass — never delete unsynced results.

Destination is iridis **scratch** for now, moving to `/iridisfs/ddnb/luke/kitsune/` once space allows. Make the destination a config value, not a literal, so that move is a one-line change. Whole-cohort output is expected in the 20–200 GB range.

Because iridis scratch is likely subject to auto-purge, add a `kitsune sync --all` command that can re-push every result from the PGX copy, and keep the PGX `results/` tree as the master.

---

## 10. Config

Single YAML, no hardcoded paths:

```yaml
paths:
  refs: /data/kitsune/refs
  scratch: /scratch/kitsune/work
  results: /data/kitsune/results
  ledger: /data/kitsune/ledger/kitsune.db
remote:
  host: iridis
  user: <user>
  dest: /scratch/<user>/kitsune/results     # later: /iridisfs/ddnb/luke/kitsune/results
limits:
  concurrency: 2
  threads_per_job: 16
  min_free_gb: 200
  max_attempts: 3
  heartbeat_timeout_min: 30
options:
  emit_audit_cram: true
  verify_md5: true
  confirm_chemistry_by_whitelist: true
```

---

## 11. Concurrency and sample grouping

- A **sample** may comprise several SRRs (multiple lanes). Group by `sample_id`; pass all its R1/R2 pairs to STAR as comma-separated lists in one invocation. Claim at sample granularity, not run granularity.
- Concurrency is bounded by `min(disk_budget / expected_sample_size, RAM / index_size, cores / threads_per_job)`. On 1.8 TB, disk is not the binding constraint — **RAM is**. Start at `concurrency: 2` and raise only after measuring.
- A single reaper process handles stale claims; do not let workers reap each other.

---

## 12. CLI

```
kitsune init-db            --manifest cohort.tsv
kitsune build-refs                                  # indexes + REFERENCE_MANIFEST.json
kitsune run                [--once] [--limit N] [--tier 1]
kitsune reap                                        # return stale claims
kitsune status             [--by-gse] [--by-state]
kitsune retry              --srr SRR... | --state FAILED
kitsune sync               [--all]
kitsune verify             --sample SID             # re-check outputs vs provenance
```

`kitsune run` with no arguments is the unattended loop: claim, process, clean, repeat until no `PENDING` rows remain.

---

## 13. Failure policy

| Situation | Action |
|---|---|
| Download md5 mismatch | Retry twice, then `FAILED` |
| Ambiguous read layout | `SKIPPED` — record observed lengths |
| Unrecognised chemistry | `SKIPPED` — never guess |
| STAR non-zero exit | `FAILED` with the last 50 lines of `Log.out` in `last_error` |
| Disk below threshold | Release claim, sleep, retry — not a failure |
| Sync failure | Keep results, retry later; do not delete |
| `attempts >= max_attempts` | `QUARANTINE`, excluded from the queue until manually reset |

Everything that stops a sample must leave a row explaining why. A silent skip is a bug.

---

## 14. Tests to write first

1. **Ledger concurrency** — two workers against one PENDING row claim it exactly once.
2. **Resumability** — kill mid-`ALIGNING`; the reaper returns it; reprocessing yields byte-identical h5ad.
3. **Cleanup** — scratch is empty after both success and induced failure.
4. **Read-role detection** — synthetic FASTQ sets with 26/28/8/91 bp reads in shuffled filename order resolve correctly.
5. **Chemistry guard** — a v2 library must not be processed with v3 parameters; assert `SKIPPED` when lengths are inconsistent.
6. **Reference identity** — altering the reference manifest changes `ref_manifest_sha` and is visible in `provenance.json`.
7. **Correctness against known output** — reprocess GSE218184 and compare cell counts and per-gene sums against the existing result. This is the acceptance test; run it before anything else is trusted.

---

## 15. Non-goals

Not part of this pipeline: cell-type annotation, compartment masking, pseudobulk, integration, or any analysis. Those run on iridis against the synced h5ads. This component's only job is to turn accessions into trustworthy, provenance-tagged matrices and then forget everything else.

---

## 16. Open items to confirm before building

- PGX RAM and core count — sets concurrency and whether both indexes can be resident.
- iridis scratch auto-purge window — sets how aggressively results must be moved onward.
- Which studies are `OPEN_FASTQ` vs BAM-only vs controlled-access (run the ENA access report first; it determines how much of §4's fallback path is actually needed).
- Final contents of `audit_regions.bed`.
