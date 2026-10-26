#!/usr/bin/env bash
# Run on PGX inside tmux: keeps polling Iridis ALIGNING jobs and claiming PENDING runs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KITSUNE="${ROOT}/bin/kitsune"
LOG="${HOME}/kitsune/logs/worker.log"
mkdir -p "$(dirname "$LOG")"
cd "$ROOT"
export KITSUNE_CONFIG="${ROOT}/config.pgx.yaml"
SLEEP="${KITSUNE_WORKER_SLEEP_SEC:-120}"

echo "[$(date -Is)] worker loop start (sleep=${SLEEP}s)" | tee -a "$LOG"
while true; do
  "$KITSUNE" reap >>"$LOG" 2>&1 || true
  "$KITSUNE" status >>"$LOG" 2>&1 || true
  "$KITSUNE" study-report >>"$LOG" 2>&1 || true
  "$KITSUNE" merge-studies >>"$LOG" 2>&1 || true
  "$KITSUNE" run --once >>"$LOG" 2>&1 || true
  sleep "$SLEEP"
done
