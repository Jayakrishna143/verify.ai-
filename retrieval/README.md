# retrieval

Step 3. Runtime hybrid search over the ingested chunks.

Loads `ingest/chunks.jsonl` into an **embedded** Qdrant collection (no server,
no Docker — persists to `qdrant_data/`). Each chunk gets two vectors: a dense
vector (`bge-large-en-v1.5`, meaning) and a BM25 sparse vector (exact tokens
like tickers and line items). A query runs both searches and merges them with
RRF (k=60), returning a ranked list of chunks.

Both models run locally through **fastembed** (ONNX, no torch — see Decision 9).

- **Input:** `ingest/chunks.jsonl`.
- **Output:** `search.search(query)` → ranked `list[dict]`, each the full chunk
  payload (`doc_id`, `section_id`, `line_item`, `text`, ...) plus a `score`.
  This is what `pipeline/` imports; the citation anchors ride along untouched.

## Use

    uv run python -m retrieval.run                 # self-checks only (fast, offline)
    uv run python -m retrieval.run --build         # build the on-disk index (once)
    uv run python -m retrieval.run --build --force # rebuild from scratch
    uv run python -m retrieval.run "current ratio of JPMorgan"

The first `--build` or query downloads the bge-large + BM25 models once.

## Parameters (see config.py)

| Value | Setting |
|-------|---------|
| Dense model | `BAAI/bge-large-en-v1.5`, 1024-dim, cosine |
| Sparse model | `Qdrant/bm25` with the IDF modifier |
| Prefetch per side | 40 |
| Final (fused) | 20 |
| Fusion | RRF, k=60 (Qdrant default) |

The cross-encoder reranker is optional and not built yet. Add it later as a
post-step in `search.py`; it does not touch the index.

See `docs/research/step-3-hybrid-retrieval.md`.
