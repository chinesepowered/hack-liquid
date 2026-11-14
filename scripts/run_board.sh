#!/usr/bin/env bash
# Start Capy Tower on the IQ-9075. Run from the repo root on the board, after the hackathon setup:
#   GenieX serving LiquidAI/LFM3-1.7B-GGUF:Q4_0 on 127.0.0.1:18181 (serve.sh run, in another terminal)
#   d1-2B snapshot at ~/models/d1-2B and the d1 venv at ~/.venvs/d1 (examples/system-one-decision)
# Extra flags pass through, e.g.  scripts/run_board.sh --gate rule   or   --max-side 384
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${CAPY_PY:-$HOME/.venvs/d1/bin/python}"
if [ ! -x "$PY" ]; then
  echo "d1 venv not found at $PY; falling back to python3 with the rule gate" >&2
  PY=python3
  set -- --gate rule "$@"
fi

if curl -s -m 2 http://127.0.0.1:18181/v1/models >/dev/null; then
  echo "GenieX: up on 127.0.0.1:18181"
else
  echo "GenieX: NOT reachable on 127.0.0.1:18181. Start it first (serve.sh run); radio calls fall back to templates until it is up." >&2
fi

if [ -d "$HOME/models/d1-2B" ]; then echo "d1-2B snapshot: $HOME/models/d1-2B"; else echo "d1-2B snapshot missing at ~/models/d1-2B (app will use the rule gate)" >&2; fi
ip route | grep -q '^default' && echo "Network: an uplink is present (fine for setup; the demo runs with it off)" || echo "Network: no uplink. Offline."

exec "$PY" capy_tower/app.py "$@"
