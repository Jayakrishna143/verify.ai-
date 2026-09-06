# retrieval

Step 3. Runtime hybrid search over the ingested chunks.

Loads `ingest/chunks.jsonl` into an **embedded** Qdrant collection (no server,
no Docker — persists to `qdrant_data/`). Each chunk gets two vectors: a dense
vector (`bge-base-en-v1.5`, meaning) and a BM25 sparse vector (exact tokens
like tickers and line items). A query runs both searches and merges them with
RRF (k=60), returning a ranked list of chunks.

Both models run locally through **fastembed** (ONNX, no torch — see Decision 9).

**The index is built on Colab GPU, not locally.** The build machine is too small
to embed 9,992 chunks in reasonable time, so `colab_build_index.py` (repo root)
embeds them on a GPU and produces `qdrant_data/`, which you download and unzip
into this folder. Local `--build` still works but is slow; prefer the Colab path.

- **Input:** `ingest/chunks.jsonl`.
- **Output:** `search.search(query)` → ranked `list[dict]`, each the full chunk
  payload (`doc_id`, `section_id`, `line_item`, `text`, ...) plus a `score`.
  This is what `pipeline/` imports; the citation anchors ride along untouched.

## Use

    uv run python -m retrieval.run                 # self-checks only (fast, offline)
    uv run python -m retrieval.run --build         # build the on-disk index (once)
    uv run python -m retrieval.run --build --force # rebuild from scratch
    uv run python -m retrieval.run "current ratio of JPMorgan"

The first `--build` or query downloads the bge-base + BM25 models once. To load a
Colab-built index instead of running `--build`, unzip `qdrant_data.zip` into this
folder so `retrieval/qdrant_data/collection/` exists, then query directly.

## Parameters (see config.py)

| Value | Setting |
|-------|---------|
| Dense model | `BAAI/bge-base-en-v1.5`, 768-dim, cosine (see Decision 10 — hardware limit) |
| Sparse model | `Qdrant/bm25` with the IDF modifier |
| Prefetch per side | 40 |
| Final (fused) | 20 |
| Fusion | RRF, k=60 (Qdrant default) |

The cross-encoder reranker is optional and not built yet. Add it later as a
post-step in `search.py`; it does not touch the index.

See `docs/research/step-3-hybrid-retrieval.md`.
