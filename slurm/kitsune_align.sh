#!/usr/bin/env bash
#SBATCH --job-name=kitsune_align
#SBATCH --nodes=1
# Log paths set at submit time via sbatch --output/--error (see align_submit.py).
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --time=12:00:00
#SBATCH --partition=amd

set -euo pipefail

: "${GSE:?}"
: "${SRR:?}"
: "${SAMPLE_ID:?}"
: "${KITSUNE_ROOT:?}"

ROOT="${KITSUNE_ROOT}"
STAGING="${ROOT}/staging/${GSE}/${SAMPLE_ID}"
OUT="${ROOT}/results/${GSE}/${SAMPLE_ID}"
WORK="${ROOT}/work/${SAMPLE_ID}"
REPO="${ROOT}/repo/kitsune-pgx"
SCRIPT="${REPO}/scripts/align_sample.py"

GENCODE_IDX="${GENCODE_IDX:-/iridisfs/ddnb/Luke/kitsune/download_align_data/reference_sources/STAR_index_gencode49}"
NONCODE_IDX="${NONCODE_IDX:-/iridisfs/ddnb/Luke/kitsune/download_align_data/NONCODE/STAR_index}"
WL_V2="${WL_V2:-/iridisfs/ddnb/Luke/kitsune/download_align_data/cellranger-10.0.0/lib/python/cellranger/barcodes/737K-august-2016.txt}"
WL_V3="${WL_V3:-/iridisfs/ddnb/Luke/kitsune/download_align_data/cellranger-10.0.0/lib/python/cellranger/barcodes/3M-february-2018_TRU.txt.gz}"
REF_FA="${REF_FA:-/iridisfs/ddnb/Luke/kitsune/download_align_data/reference_sources/Homo_sapiens.GRCh38.dna.primary_assembly.fa}"
APPTAINER_IMG="${APPTAINER_IMG:-/iridisfs/ddnb/images/bionemo-framework_nightly}"
THREADS="${THREADS:-16}"

mkdir -p "${OUT}" "${WORK}" "${ROOT}/logs"
rm -rf "${WORK}/star_tmp" "${WORK}/noncode_star"

# STAR --outTmpDir on scratch (visible inside apptainer via -B /iridisfs). Avoid binding host /tmp into apptainer.
STAR_TMP="${WORK}/star_tmp"
rm -rf "${STAR_TMP}"
mkdir -p "${WORK}"
export STAR_TMPDIR="${STAR_TMP}"
echo "STAR_TMPDIR=${STAR_TMPDIR}"

echo "[$(date -Is)] kitsune_align GSE=${GSE} SRR=${SRR} SAMPLE=${SAMPLE_ID}"
echo "NOTE: STARsolo is CPU-only; any NVIDIA driver message from the Python image is harmless."

module load star/2.7.11b
module load samtools
module load apptainer 2>/dev/null || true

export STAR_BIN="$(command -v STAR)"
STAR_PATH="$(dirname "${STAR_BIN}")"
export PATH="${STAR_PATH}:${PATH}"

echo "STAR=${STAR_BIN}"

# Host STAR; scanpy/anndata in apptainer. Host samtools cannot run inside the image (libcrypto).
apptainer exec -B /iridisfs:/iridisfs \
  --env STAR_BIN="${STAR_BIN}" \
  --env KITSUNE_SKIP_SAMTOOLS=1 \
  --env STAR_TMPDIR="${STAR_TMPDIR}" \
  --env PATH="${PATH}" \
  "${APPTAINER_IMG}" \
  python "${SCRIPT}" \
  --staging "${STAGING}" \
  --out "${OUT}" \
  --work "${WORK}" \
  --gse "${GSE}" \
  --srr "${SRR}" \
  --sample-id "${SAMPLE_ID}" \
  --gencode-idx "${GENCODE_IDX}" \
  --noncode-idx "${NONCODE_IDX}" \
  --wl-v2 "${WL_V2}" \
  --wl-v3 "${WL_V3}" \
  --ref-fa "${REF_FA}" \
  --threads "${THREADS}"

BAM="${OUT}/gencode/${SRR}_Aligned.sortedByCoord.out.bam"
CRAM="${OUT}/audit/${SAMPLE_ID}.loci.cram"
if [[ -f "${BAM}" && ! -f "${CRAM}" ]]; then
  echo "[$(date -Is)] CRAM on host (samtools module)"
  samtools index "${BAM}"
  samtools view -C -T "${REF_FA}" -o "${CRAM}" "${BAM}"
  samtools index "${CRAM}"
  rm -f "${BAM}" "${BAM}.bai"
fi

echo "[$(date -Is)] done ${OUT}/provenance.json"
