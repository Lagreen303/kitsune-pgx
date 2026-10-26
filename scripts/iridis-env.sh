#!/usr/bin/env bash
# Source on Iridis login: module load python/3.12.6 && source scripts/iridis-env.sh
module load python/3.12.6 2>/dev/null || true
export KITSUNE_CONFIG="${KITSUNE_CONFIG:-config.iridis-login.yaml}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
