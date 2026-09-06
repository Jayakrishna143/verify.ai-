"""Constants for the retrieval step. No logic here — just values the other
retrieval modules read. Mirrors ingest/config.py."""

import os
from pathlib import Path

# ponytail: fastembed defaults its model cache to /tmp/fastembed_cache, but on
# WSL /tmp is a ~950 MB tmpfs, so a model download can die with "No space left
# on device". Point it at the persistent home cache on the root fs. index.py and
# search.py both import this module first, so they share one cache and download
# the model once. Disable the HF xet downloader too — it stages files through
# /tmp regardless.
os.environ.setdefault("FASTEMBED_CACHE_PATH", str(Path.home() / ".cache" / "fastembed"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from ingest import config as ingest_cfg

# --- Paths -------------------------------------------------------------------
RETRIEVAL_DIR = Path(__file__).resolve().parent
CHUNKS = ingest_cfg.CHUNKS  # ingest/chunks.jsonl — do not re-derive the path.
# Embedded Qdrant persists here (Decision 9). Built artifact, git-ignored.
QDRANT_PATH = RETRIEVAL_DIR / "qdrant_data"
COLLECTION = "filings"

# --- Models (Decision 5 + 9) -------------------------------------------------
# fastembed runs both locally (ONNX, no torch). Dense carries meaning, sparse
# carries exact tokens (tickers, line items).
# bge-base, not bge-large: this WSL VM has 2 cores and 1.9 GB RAM. bge-large
# (1.3 GB) swapped and crashed the VM. bge-base (~440 MB) loads fine here for
# per-query embedding. The heavy corpus embedding runs on Colab GPU
# (colab_build_index.py) — the built index drops into qdrant_data/. This model
# must match the one colab_build_index.py used to build. See Decision 10.
DENSE_MODEL = "BAAI/bge-base-en-v1.5"  # 768-dim, cosine
DENSE_DIM = 768
SPARSE_MODEL = "Qdrant/bm25"  # IDF-weighted BM25 sparse

# --- Retrieval parameters (step-3 research) ----------------------------------
PREFETCH_LIMIT = 40  # per sub-search (dense, sparse), before fusion
FINAL_LIMIT = 20  # after RRF fusion
# Qdrant's RRF defaults to k=60 (the SIGIR-2009 paper value), so FusionQuery
# needs no explicit k. Kept here as the documented value.
RRF_K = 60
UPSERT_BATCH = 128
# ponytail: cross-encoder reranker skipped (research says optional). Add a
# rerank() post-step in search.py later; it does not touch the index.
