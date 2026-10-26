#!/usr/bin/env bash
# Optional: only for interactive bash. Prefer: ~/kitsune-pgx/bin/kitsune status
REPO="${KITSUNE_REPO:-$HOME/kitsune-pgx}"
cd "$REPO" || exit 1
# shellcheck disable=SC1091
. "$REPO/.venv/bin/activate"
export KITSUNE_CONFIG="${KITSUNE_CONFIG:-$REPO/config.pgx.yaml}"
