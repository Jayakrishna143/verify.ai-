# verify_ai

A verifiable question-answering pipeline for SEC EDGAR financial filings.
The system answers financial questions about public companies and attaches a
source citation to every number it returns. Each citation includes the filing
ID, the page, and the line item so a person can check it by hand.

**The pipeline never computes a final number in free text.** Every number goes
through a deterministic tool function. This is the core design rule.

---

## What it does

1. A user asks a financial question, for example "What was JPMorgan's current
   ratio in FY2025?"
2. The LangGraph pipeline makes the language model write a numbered plan before
   it takes any action.
3. The retrieval layer finds the relevant chunks from SEC EDGAR filings using
   hybrid keyword and vector search.
4. The pipeline forces the model to call a deterministic tool function. The
   function reads the XBRL data and computes the number.
5. The system returns the answer with a citation that names the filing, the
   page, and the line item.

A correct answer with a wrong or missing citation is a failure. The pipeline
treats citation accuracy as equal to numeric accuracy.

---

## Corpus

The pipeline covers 15 finance-sector companies. For each company it holds
the latest annual report (10-K) and the two most recent quarterly reports
(10-Q). That is approximately 45 filings.

| Ticker | Company |
|--------|---------|
| JPM | JPMorgan Chase |
| BAC | Bank of America |
| GS | Goldman Sachs |
| MS | Morgan Stanley |
| USB | U.S. Bancorp |
| PNC | PNC Financial Services |
| COF | Capital One |
| AXP | American Express |
| V | Visa |
| MA | Mastercard |
| BLK | BlackRock |
| SCHW | Charles Schwab |
| MET | MetLife |
| TRV | Travelers Companies |
| CB | Chubb |

---

## Architecture

The project has five folders. Each folder has one role. The two handoffs
between folders are plain files.

```
ingest/     Download filings, chunk them, write ingest/chunks.jsonl
retrieval/  Hybrid search (BM25 + dense vectors) over the chunks
tools/      One deterministic function per metric, exposed as forced tool calls
pipeline/   LangGraph graph: plan → retrieve → tool call → cite
api/        FastAPI backend + SQLite conversation store
frontend/   Vanilla HTML/JS chat UI (no framework)
```

Data flow: `ingest/` writes `chunks.jsonl`. `retrieval/` indexes it into
Qdrant. `pipeline/` calls `retrieval/` to find chunks and `tools/` to compute
numbers. `api/` drives the pipeline per request. `frontend/` talks to `api/`.

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12 | Runtime |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | latest | Package and venv manager |
| tmux | any | Keep the server alive in WSL or a remote shell |

You also need at least one API key. The pipeline defaults to Gemini free tier.

| Variable | Required | Notes |
|----------|----------|-------|
| `GEMINI_API_KEY` | Default path | Free tier. Get one at [aistudio.google.com](https://aistudio.google.com) |
| `ANTHROPIC_API_KEY` | Opt-in only | Only needed when `LLM_PROVIDER=claude` |

---

## Local setup

### 1. Clone the repository

```bash
git clone https://github.com/Jayakrishna143/verify.ai-.git
cd verify.ai-
```

### 2. Install dependencies

```bash
make install
```

This runs `uv sync` and creates a `.venv` at the repo root.

### 3. Set environment variables

Create a `.env` file in the repo root:

```
GEMINI_API_KEY=your_key_here
```

To use Claude instead of Gemini on a specific run, add:

```
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=your_key_here
```

### 4. Download and index the corpus

```bash
make ingest
```

This runs two steps in order:

- **download** — fetches the 45 filings from SEC EDGAR and writes them to
  `data/corpus/`. This step also runs the chunker and writes
  `ingest/chunks.jsonl`. It respects the SEC fair-access rate limit of 10
  requests per second.
- **index** — loads `ingest/chunks.jsonl` into an embedded Qdrant collection
  at `retrieval/qdrant_data/`. The first run also downloads the
  `bge-large-en-v1.5` embedding model (~1.3 GB). This model runs locally.
  No API key is needed.

Run the two steps separately if you want:

```bash
make download   # fetch filings + chunk
make index      # build the Qdrant index
```

To rebuild the index from scratch:

```bash
make index-force
```

### 5. Start the server

```bash
make serve
```

This starts `uvicorn` inside a tmux session named `verifyai`. Open a browser
and go to `http://localhost:8000`. The chat UI loads immediately.

To stop the server:

```bash
make stop
```

---

## Makefile reference

| Target | What it does |
|--------|-------------|
| `make install` | Install all Python dependencies with uv |
| `make download` | Download SEC filings from EDGAR and chunk them |
| `make chunk` | Re-chunk an already-downloaded corpus (skip the download) |
| `make index` | Build the Qdrant hybrid search index |
| `make index-force` | Rebuild the index from scratch |
| `make ingest` | Run download then index (full data setup) |
| `make serve` | Start the API server at http://localhost:8000 |
| `make stop` | Stop the API server |
| `make check` | Run self-checks on the retrieval layer |
| `make clean` | Remove all `__pycache__` directories |

---

## Project structure

```
verify_ai/
├── api/              FastAPI backend, SQLite conversation store
├── data/corpus/      SEC EDGAR HTML filings (gitignored, rebuilt by make download)
├── frontend/         index.html — the full chat UI
├── ingest/           Downloader, chunker, and output chunks.jsonl
├── pipeline/         LangGraph graph definition
├── retrieval/        Qdrant index builder and hybrid search
├── tools/            metrics.yaml + one Python function per metric
├── .env              API keys (gitignored, create this yourself)
├── Makefile          All build and run commands
└── pyproject.toml    Python dependencies
```

---

## How the citation works

Every number the pipeline returns carries three fields:

| Field | Example | What it points to |
|-------|---------|-------------------|
| `doc_id` | `JPM-10-K-FY2025` | The specific filing |
| `page` | `47` | The page in that filing |
| `line_item` | `us-gaap:AssetsCurrent` | The XBRL tag for the number |

These fields come from the chunk metadata that `ingest/` attaches at index
time. If a chunk loses its page or line item during ingestion, no later step
can recover them. The chunker never splits a table across two chunks.

---

## Notes for WSL users

The `make serve` command uses tmux to keep the server alive. A background
process started with `nohup &` dies when the WSL bash session ends. The tmux
session survives.

If port 8000 is already in use, stop the existing session first:

```bash
make stop
make serve
```
