# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A small verifiable AI pipeline for SEC EDGAR financial filings. Claude reads a
question and writes a plan. A separate deterministic system holds the data, runs
the math, and attaches a source citation to every number. **Claude never
computes a final number in free text.** Every number a user sees points back to
a filing, a page, and a line item that a person can check by hand.

This rule is the whole point of the project. Do not let a number reach the final
answer without a `doc_id`, a `page`, and a `line_item`.

## Current state

Pre-code. The repo holds the research (`docs/research/`, 8 step reports), the
decision log (`decisions.md`), and empty scaffold folders each with a README.
There is no build system, no tests, and no dependencies installed yet. Do not
invent commands — when you add tooling, record the choice in `decisions.md`.

**Read `decisions.md` first.** It records why the folders are grouped the way
they are and what is still open.

## Architecture

The pipeline is 5 folders, mapped from the 8 research steps. The split is by
lifecycle and dependency, not one folder per step. The two handoffs between
folders are plain files.

| Folder | Steps | Role | Lifecycle |
|--------|-------|------|-----------|
| `ingest/` | 1 + 2 | Download filings, chunk them, label each chunk with page + section id. Writes `chunks.jsonl`. | Run once, offline. |
| `retrieval/` | 3 | Hybrid search (Qdrant sparse BM25 + dense vectors, RRF merge) over `chunks.jsonl`. | Runtime service. Needs Qdrant + an embedding model. |
| `tools/` | 4 + 5 | `metrics.yaml` (ontology: one formula per metric) plus one deterministic function per formula, exposed to Claude as forced tool calls. | Pure functions. |
| `pipeline/` | 6 + 7 | The request handler, built as a LangGraph graph: drive the LLM (plan first, stop on ambiguity, force a tool call), then format the answer with a citation trace. | Runtime, per question. |
| `eval/` | 8 | Test harness on top of the whole pipeline. `questions.jsonl` answer key + runner. Imports nothing back into the pipeline. | Test only. |

Data flow: `ingest/` → `chunks.jsonl` → `retrieval/`. `pipeline/` calls
`retrieval/` to find chunks and `tools/` to compute numbers. `eval/` runs the
whole thing against a known answer key.

Raw filings live in `data/corpus/` (output of `ingest/` step 1).

## Framework and LLM providers

- **LangGraph is the agent framework.** Build the `pipeline/` request handler as
  a LangGraph graph: nodes for plan, ambiguity check, retrieve, tool call, and
  format. This replaces the plain system-prompt loop the research proposed as a
  first pass. Use LangGraph `interrupt()` for the stop-and-ask escalation so the
  pause is a real, unskippable graph state, not a soft prompt rule. Use LangChain
  for the model wrappers and `bind_tools`.
- **The workflow is not Claude-only, and it prefers free.** Do not hard-code
  Anthropic. Default to the free option. Use Claude only as an occasional opt-in.
  Select the provider at runtime:
  - **Default:** Gemini free tier when `GEMINI_API_KEY` is set. Use a free-tier
    model (a Flash-class model). This carries most runs.
  - **Opt-in:** Claude only when the run explicitly asks for it (for example
    `LLM_PROVIDER=claude`) and `ANTHROPIC_API_KEY` is set. The Claude key is
    scarce, so keep it for the occasional permitted run, not the default path.
  Wire this through one LangChain chat-model factory (for example
  `init_chat_model`, or `ChatAnthropic` / `ChatGoogleGenerativeAI`) so the rest
  of the graph does not care which provider is active. Keep the deterministic
  `tools/` layer provider-agnostic — it never changes with the model.
- **Embeddings are free and local.** Use `bge-large-en-v1.5` through
  `sentence-transformers`. No API key, no rate limit, and the corpus never leaves
  the machine. This is the default. A free-tier hosted embedding (for example a
  Gemini embedding model) is only a fallback if local embedding is not practical.
- **Respect free-tier limits.** Gemini free tier has per-minute and per-day
  request caps. Throttle the `eval/` runner (add a small delay between the 20-30
  questions) so a full eval pass stays under the cap. Local embeddings have no
  cap, so retrieval never hits this limit.
- **Provider caveats to handle in code:**
  - Forced tool use works on both providers through LangChain `bind_tools`
    (`tool_choice`), so the "LLM must call a tool, never free-text math" rule
    holds either way.
  - Native Claude Citations (step 7) is Anthropic-only. On Gemini, fall back to
    the custom citation trace, which is already the recommended backbone. The
    custom trace, not a provider feature, is the source of truth for provenance.

## Rules that shape the code

- **`tools/` is the only place numbers are computed.** Each metric is one pure
  function forced through a Claude `tool_choice` call. Test each function alone
  with fixed input and asserted output before wiring it to Claude.
- **`metrics.yaml` and the functions must stay in sync.** The formula in the
  YAML and the function that runs it are two views of one thing. That is why
  they share the `tools/` folder. Input names borrow US-GAAP XBRL tags (e.g.
  `us-gaap:AssetsCurrent`) so they map one-to-one onto the EDGAR `companyfacts`
  API with no translation layer.
- **Citation over convenience.** A run passes only when the number is within
  tolerance AND the citation matches the expected source. A correct number with
  a wrong or missing citation is a failure.
- **Chunking decides citation quality.** `ingest/` must keep `page` and
  `section_id` on every chunk. If they are dropped there, no later step can
  recover them. Do not split a table across two chunks.
- **Plan then execute.** `pipeline/` makes Claude write a numbered plan before
  any tool call, and stop and ask on an ambiguous term (e.g. "margin",
  "current", "earnings"). Do not let it guess.

## Key research recommendations (see `docs/research/` for the reasoning)

- Corpus: SEC EDGAR 10-K/10-Q + XBRL, 10-20 docs, under 50 files. Requests need
  a `User-Agent` header (name + email) and stay under 10 requests/second.
- Parser: bs4 + lxml for SEC HTML (Docling was tried and removed — too slow and
  mangled the iXBRL tables, see Decision 7). 512-token chunks, ~64-token overlap,
  `section_id` from detected headings. Re-add Docling only for future PDF filings.
- Retrieval: Qdrant native hybrid, RRF fusion (k=60), `bge-large-en-v1.5`
  embeddings (1024-dim, local, free), top-k 40 per prefetch → 20 fused.
- Model: Gemini free tier by default, Claude as an occasional opt-in (see
  Framework and LLM providers). On Claude, use adaptive thinking (forced tool use
  is not supported with manual extended thinking).
- Eval: plain JSONL answer key + a small stdlib runner. No hosted service.

## Open items

- Confirm the Apple FY2023 current-ratio answer key against the real filing
  before locking it. The example shows the shape, not the exact digits.
- The cross-encoder reranker in `retrieval/` is optional. Skip at the start.
- Confirm Gemini free-tier limits and pick the exact free model at build time.

## Writing style for docs and reports

Prose in this repo follows Simplified Technical English: short sentences, active
voice, one name per thing, no marketing adjectives. Match the tone of the
existing `docs/research/` files and `decisions.md`.
