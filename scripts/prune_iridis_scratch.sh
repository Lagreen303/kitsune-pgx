#!/usr/bin/env bash
# Remove bulky STAR artifacts; keep h5ad, provenance, audit CRAM.
set -euo pipefail
ROOT="${1:-/iridisfs/scratch/lag1e24/kitsune}"
RESULTS="${ROOT}/results"

echo "[$(date -Is)] prune scratch under ${ROOT}"
du -sh "${ROOT}" 2>/dev/null || true

rm -rf "${ROOT}/staging"/* "${ROOT}/work"/* 2>/dev/null || true
mkdir -p "${ROOT}/staging" "${ROOT}/work"

if [[ -d "${RESULTS}" ]]; then
  find "${RESULTS}" -type d -name '*_Solo.out' -prune -exec rm -rf {} + 2>/dev/null || true
  find "${RESULTS}" -type f \( \
    -name '*_Log.final.out' -o -name '*_Log.out' -o -name '*_Log.progress.out' -o \
    -name '*_SJ.out.tab' -o -name '*Aligned.sortedByCoord.out.bam' -o \
    -name '*Aligned.sortedByCoord.out.bam.bai' \
  \) -delete 2>/dev/null || true
fi

echo "[$(date -Is)] after prune:"
du -sh "${ROOT}" "${RESULTS}" 2>/dev/null || true
exit 0
