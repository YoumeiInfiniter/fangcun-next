#!/usr/bin/env bash
# Generic Fangcun draft wrapper. Usage:
#   FANGCUN_CONFIG=/path/to/project/drama/config.json ./agent_cmd.sh save 1 /tmp/ep1.txt
set -euo pipefail
CONFIG="${FANGCUN_CONFIG:-${1:-}}"
if [[ -z "${CONFIG}" || ! -f "${CONFIG}" ]]; then
  echo "Usage: FANGCUN_CONFIG=/path/to/config.json $0 save|validate|pass|blocked|confirm|context <ep> [file] [reason]" >&2
  exit 2
fi
if [[ "${1:-}" == "${CONFIG}" ]]; then shift; fi
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CMD="${1:-}"; EP="${2:-}"; FILE="${3:-}"; REASON="${4:-}"
cd "$TOOLS"
case "$CMD" in
  save) python3 pipeline.py --config "$CONFIG" --save-draft --episode "$EP" --file "$FILE" --skip-review-gate ;;
  validate) python3 pipeline.py --config "$CONFIG" --validate-draft --episode "$EP" --skip-review-gate ;;
  pass) python3 pipeline.py --config "$CONFIG" --mark-pass --episode "$EP" --skip-review-gate ;;
  blocked) python3 pipeline.py --config "$CONFIG" --mark-blocked --episode "$EP" --reason "$REASON" --skip-review-gate ;;
  confirm) python3 pipeline.py --config "$CONFIG" --confirm-draft-batch --skip-review-gate ;;
  context) python3 pipeline.py --config "$CONFIG" --get-context --episode "$EP" --skip-review-gate 2>&1 | tail -300 ;;
  *) echo "Unknown command: $CMD" >&2; exit 2 ;;
esac
