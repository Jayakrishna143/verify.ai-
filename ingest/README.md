# ingest

Steps 1 + 2. Run-once offline batch that prepares the corpus.

- **Step 1** (`download.py`) resolves the 15 tickers to CIKs (live, from
  `company_tickers.json`), downloads 1 × 10-K + 2 × 10-Q per company plus the
  XBRL companyfacts JSON, and writes `manifest.jsonl`. Raw files go to
  `../data/corpus/`.
- **Step 2** (`chunk.py`) strips each filing to text with bs4, detects the SEC
  section heading, and packs ~512-token chunks with page + section metadata.

**Outputs:** `manifest.jsonl` (one row per document) and `chunks.jsonl` (read by
`retrieval/`). Numbers are cited later from the companyfacts JSON, not from chunk
text — chunks locate human-readable context.

## Run

```
cd /home/jaya/office/verify_ai
uv python install 3.12
uv sync
uv run python -m ingest.run          # self-checks, then download + chunk
uv run python -m ingest.run --chunk  # skip download, re-chunk only
```

See `docs/research/step-1-choose-domain-and-corpus.md`,
`docs/research/step-2-index-with-source-metadata.md`, and Decisions 6-7 in
`../decisions.md` (why bs4 replaced Docling for HTML).
