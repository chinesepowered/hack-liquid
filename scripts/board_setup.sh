#!/usr/bin/env bash
# One-time setup of a fresh IQ-9075 for Capy Tower, following the hackathon developer guide.
# Run on the board while it has internet. Two independent parts, safe to run in parallel:
#   SUDO_PW=... scripts/board_setup.sh geniex   NPU packages, fastrpc group, GenieX v0.10.0, LFM3-1.7B Q4_0
#   scripts/board_setup.sh d1                   uv, d1 venv (Transformers, CPU torch), pinned d1-2B snapshot
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
HACK=~/cleared-for-takeoff-hackathon

geniex_part() {
  : "${SUDO_PW:?set SUDO_PW to the board password}"
  S() { echo "$SUDO_PW" | sudo -S -p '' "$@"; }
  S apt-get update -q
  S env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libatomic1 qcom-fastrpc1 libqnn1 libglib2.0-0t64 ocl-icd-libopencl1
  if getent group fastrpc >/dev/null; then S usermod -aG fastrpc "$USER"; fi
  ls -l /dev/fastrpc-cdsp*
  cd ~ && curl -fSLo install.sh https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-geniex/install.sh
  sh install.sh --version v0.10.0
  grep -q 'local/bin' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
  geniex version
  geniex --skip-update list | grep -q 'LFM3-1.7B' || geniex --skip-update pull LiquidAI/LFM3-1.7B-GGUF:Q4_0
  geniex --skip-update list
  echo GENIEX_SETUP_DONE
}

d1_part() {
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  [ -d "$HACK" ] || git clone -q --depth 1 https://github.com/heath0xFF/cleared-for-takeoff-hackathon "$HACK"
  [ -x ~/.venvs/d1/bin/python ] || uv venv --system-site-packages --python /usr/bin/python3 ~/.venvs/d1
  # CPU-only torch: the default aarch64 wheels pull gigabytes of CUDA libraries the board cannot use.
  uv pip install --python ~/.venvs/d1/bin/python --index-url https://download.pytorch.org/whl/cpu torch==2.11.0 torchvision==0.26.0
  uv pip install --python ~/.venvs/d1/bin/python "transformers>=5.19" pillow packaging huggingface_hub
  ~/.venvs/d1/bin/python -c 'import torch, torchvision, transformers, PIL; print(torch.__version__, torchvision.__version__, transformers.__version__, PIL.__version__)'
  ~/.venvs/d1/bin/python "$HACK/examples/system-one-decision/fetch_d1.py" --dest ~/models/d1-2B
  du -sh ~/models/d1-2B
  echo D1_SETUP_DONE
}

case "${1:-}" in
  geniex) geniex_part ;;
  d1) d1_part ;;
  *) echo "usage: $0 geniex|d1" >&2; exit 2 ;;
esac
