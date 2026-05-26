#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
BILINC_DB_PATH="${BILINC_DB_PATH:-$HOME/bilinc.db}"

echo "[bilinc] Hermes bootstrap starting..."
echo "[bilinc] hermes_home=$HERMES_HOME"
echo "[bilinc] db_path=$BILINC_DB_PATH"

python3 -m bilinc.cli.main hermes bootstrap \
  --hermes-home "$HERMES_HOME" \
  --db-path "$BILINC_DB_PATH" \
  "$@"
