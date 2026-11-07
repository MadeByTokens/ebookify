#!/usr/bin/env bash
# Create (or update) the skill's private virtual environment at <skill>/.venv
# Usage: bash scripts/setup.sh [--upgrade]
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$SKILL_DIR/.venv"
REQ="$SKILL_DIR/scripts/requirements.txt"

if [[ ! -x "$VENV/bin/python" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python ">=3.10" "$VENV"
  else
    python3 -m venv "$VENV"
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV/bin/python" ${1:+--upgrade} -r "$REQ"
else
  "$VENV/bin/python" -m pip install ${1:+--upgrade} -r "$REQ"
fi

# yt-dlp breaks whenever YouTube changes things; always keep it current.
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV/bin/python" --upgrade yt-dlp >/dev/null
else
  "$VENV/bin/python" -m pip install --upgrade yt-dlp >/dev/null
fi

# NVIDIA GPU: faster-whisper needs cuBLAS + cuDNN 9 for CUDA 12. Install them as pip
# wheels (~1.5 GB) unless EBOOKIFY_NO_CUDA=1. Without them Whisper runs on CPU.
if command -v nvidia-smi >/dev/null 2>&1 && [[ -z "${EBOOKIFY_NO_CUDA:-}" ]]; then
  echo "NVIDIA GPU found: installing cuBLAS/cuDNN wheels for GPU transcription (set EBOOKIFY_NO_CUDA=1 to skip)"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV/bin/python" "nvidia-cublas-cu12" "nvidia-cudnn-cu12>=9,<10" "nvidia-cuda-runtime-cu12"
  else
    "$VENV/bin/python" -m pip install "nvidia-cublas-cu12" "nvidia-cudnn-cu12>=9,<10" "nvidia-cuda-runtime-cu12"
  fi
fi

"$VENV/bin/python" "$SKILL_DIR/scripts/check_deps.py"
