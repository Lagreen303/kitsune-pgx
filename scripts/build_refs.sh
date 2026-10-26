#!/usr/bin/env bash
# Usage: build_refs.sh [/iridisfs/scratch/YOUR_USER/kitsune]
set -euo pipefail
ROOT="${1:-${KITSUNE_ROOT:-/iridisfs/scratch/YOUR_USER/kitsune}}"
DDNB="/iridisfs/ddnb/Luke/kitsune/download_align_data"
mkdir -p "${ROOT}/refs"
echo "Copying STAR indexes (read-only ddnb → scratch). This is large and slow."
rsync -a --info=progress2 "${DDNB}/reference_sources/STAR_index_gencode49/" "${ROOT}/refs/star_index_gencode/"
rsync -a --info=progress2 "${DDNB}/NONCODE/STAR_index/" "${ROOT}/refs/star_index_noncode/"
echo "Done. Point iridis.ddnb_readonly or SLURM env at ${ROOT}/refs/ when ready."
