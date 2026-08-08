#!/usr/bin/env bash
# Generic script phase wrapper. Requires FANGCUN_CONFIG; accepts START/END/BATCH_SIZE env overrides.
set -euo pipefail
CONFIG="${FANGCUN_CONFIG:-${1:-}}"
if [[ -z "${CONFIG}" || ! -f "${CONFIG}" ]]; then
  echo "Usage: FANGCUN_CONFIG=/path/to/project/drama/config.json START=1 END=5 $0" >&2
  exit 2
fi
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$TOOLS"
python3 pipeline.py   --config "$CONFIG"   --phase script   --start "${START:-1}"   --end "${END:-${START:-1}}"   --batch-size "${BATCH_SIZE:-5}"   --skip-draft-review   --skip-review-gate
