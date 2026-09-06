#!/usr/bin/env bash
# Detached-friendly build launcher. Caps ONNX/OMP threads so the embedding of
# 9,992 chunks does not spike the WSL2 VM into a crash.
set -e
cd /home/jaya/office/verify_ai
export OMP_NUM_THREADS=2
export ORT_NUM_THREADS=2
exec uv run python -m retrieval.run --build
