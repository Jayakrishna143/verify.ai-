# Decisions

This file records the structural decisions for the verifiable AI pipeline. It
is a running log. Read it first in a new session to learn what was decided and
why. Each entry records the reason, not just the choice.

## How to use this file

- Point a new session here to catch up on decisions.
- Add one entry per structural choice. State the reason.
- Do not record small code changes here. This file is for structure and trade-offs.

---

## Project context

The project is a small verifiable AI pipeline in the Kepler Finance style.
Claude reads a question and writes a plan. A separate deterministic system
holds the data, runs the math, and cites a source for every number. Claude
never writes a final number in free text.

The domain is fixed to SEC EDGAR financial filings (Form 10-K and Form 10-Q,
with XBRL). The corpus is about 10 to 20 filings, under 50 documents, in one
folder.

The research phase produced 8 step reports in `docs/research/`. Each report
decides one thing:

1. Choose the domain and corpus.
2. Index documents with source metadata (chunk + label).
3. Build a hybrid retrieval layer (keyword + vector).
4. Write a domain ontology file (metric dictionary).
5. Build deterministic calculation tools (one function per formula).
6. Add a planning and escalation step (plan first, stop on ambiguity).
7. Attach provenance to every answer (doc id, page, line item).
8. Build an evaluation set and log every run.

---

## Decision 1 — Folder layout: 5 folders, not 8

**Date:** 2026-08-13

**Decision.** Do not use one folder per step. Group the 8 steps into 5 folders
by lifecycle and dependency.

```
verify_ai/
  data/corpus/     raw filings (output of ingest, from step 1)
  ingest/          steps 1 + 2  download filings, chunk + metadata -> chunks.jsonl
  retrieval/       step 3       Qdrant hybrid search over chunks.jsonl
  tools/           steps 4 + 5  metrics.yaml (ontology) + one function per formula
  pipeline/        steps 6 + 7  plan-then-execute loop + citation-trace answer format
  eval/            step 8       questions.jsonl + runner + diff script
  docs/research/   the 8 research reports (already here)
```

**Reason.** The research docs split by decision, which is right for research.
Code splits by lifecycle and dependency. Several steps share both, so they
share a folder. The two handoffs between folders are plain files, so the
boundaries stay clean.

### Why each group

**ingest = step 1 + step 2.** Both run once, offline, to prepare the corpus.
Step 1 downloads the filings. Step 2 chunks them and writes `chunks.jsonl`.
The handoff is a direct file. Same lifecycle, same job. No runtime code reads
them.

**retrieval = step 3, alone.** This is a runtime service. It needs Qdrant
running and an embedding model loaded. A query hits it once per question. The
dependency and the lifecycle differ from the offline batch above. It reads
`chunks.jsonl` and loads it into Qdrant, so the boundary to ingest is one file.

**tools = step 4 + step 5.** The ontology file (`metrics.yaml`) is data that
only the calculation functions read. The formula in the YAML and the function
that runs it must stay in sync. Split across two folders, they drift over time.
The deterministic math core is one thing. Keep `metrics.yaml` next to the
functions that consume it.

**pipeline = step 6 + step 7.** Both form the request handler. Step 6 drives
Claude: it makes Claude write a plan, stop on an ambiguous term, then force a
tool call. Step 7 formats the final answer and attaches the citation trace
(doc id, page, line item) to every number. They run in sequence on every
question. One request path, one folder.

**eval = step 8, alone.** This is a test harness on top of the whole pipeline.
It owns `questions.jsonl` (the answer key) and the runner. It imports nothing
back into the pipeline path. The isolation is the point. A run passes only when
the number is within tolerance AND the citation matches the expected source.

### Why 5 and not 8

Eight folders splits things that share a seam. Step 1 and step 2 are one batch.
Step 4 and step 5 are one math core. Step 6 and step 7 are one request path.
Splitting them adds folders with no real boundary between them.

### Why 5 and not 1

One folder merges things that do not share a seam. The 5 groups have different
runtimes: an offline batch, a live search service, pure deterministic
functions, the Claude orchestration loop, and a test harness. These are real
boundaries worth one folder each.

---

## Decision 2 — Scaffold the 5 folders with a README each

**Date:** 2026-08-13

**Decision.** Create the folder tree from Decision 1. Put one short README in
each folder. No code yet.

Created:

```
data/corpus/README.md    raw filings (step 1 output)
ingest/README.md         steps 1 + 2
retrieval/README.md      step 3
tools/README.md          steps 4 + 5
pipeline/README.md       steps 6 + 7
eval/README.md           step 8
```

Each README names its steps, its input and output file, and links back to the
source research docs in `docs/research/`.

**Reason.** The tree makes the boundaries real before any code exists. The
README in each folder is the single reminder of what belongs there and where
its input comes from.

**Next.** Build `ingest/` first. Everything downstream reads its `chunks.jsonl`.

---

## Decision 3 — LangGraph framework + multi-provider LLM

**Date:** 2026-08-13

We chose LangGraph as the agent framework for the `pipeline/` folder, with
LangChain for the model wrappers and tool binding. The request handler becomes a
LangGraph graph with nodes for plan, ambiguity check, retrieve, tool call, and
format. The stop-and-ask escalation uses LangGraph `interrupt()` for a real
pause, not a soft prompt rule. We also decided the workflow must not be
Claude-only: it selects the LLM provider at runtime from the environment. If
`ANTHROPIC_API_KEY` is set it uses Claude; if `GEMINI_API_KEY` is set it can
switch to Gemini. One LangChain chat-model factory hides the provider from the
rest of the graph, and the deterministic `tools/` layer stays provider-agnostic.

**Caveats we noted (not errors, but traps for later).** Forced tool use works on
both providers through LangChain `bind_tools`, so the "never free-text math" rule
holds either way. Native Claude Citations is Anthropic-only, so on Gemini the
pipeline falls back to the custom citation trace, which was already the chosen
backbone. No errors or breakage occurred this session.

We updated `CLAUDE.md` with all of the above.

---

## Decision 4 — Considered MCP for the tools, deferred it

**Date:** 2026-08-13

We asked whether the `tools/` functions should be MCP tools instead of plain
functions, so we could swap the LLM without provider-specific code. We decided
to defer MCP and keep plain Python functions bound through LangChain. The reason:
LangChain already makes the tools provider-agnostic. You write the function once,
and LangChain translates the schema to Claude or Gemini at `bind_tools` time, so
there is no per-LLM tool code to remove. MCP would add a server process and a
wire boundary, then route back through the same `bind_tools` hop, so it lands in
the same place. The real MCP win is reuse by external clients (Claude Desktop,
Cursor, other apps), which is not a goal for this project.

MCP also does not fix the two caveats from Decision 3: forced tool use still
lives at the framework and LLM layer, and native Citations stays Anthropic-only.
The upgrade path is cheap: the function is the unit, and we can wrap the same
functions with an MCP server (for example FastMCP) in about 10 lines later, with
no change downstream. So the decision is to adopt MCP only when an external
client needs the tools, not before. No errors this session.

---

## Decision 5 — Free-first: local embeddings, Gemini default, Claude occasional

**Date:** 2026-08-13

We decided the pipeline should run on free or free-tier services for most work.
Embeddings use `bge-large-en-v1.5` through `sentence-transformers`, which is
local, needs no API key, and has no rate limit, so it is the default and the
corpus stays on the machine. The LLM defaults to the Gemini free tier (a
Flash-class model) for routine runs. Claude becomes an occasional opt-in, chosen
only when the run asks for it (for example `LLM_PROVIDER=claude`), because the
Claude key is scarce and needs permission. This flips the earlier framing in
Decision 3, where the provider was picked by whichever key was present. Now the
default path is the free path, and Claude is the exception.

We also noted a limit to respect: the Gemini free tier has per-minute and
per-day caps, so the `eval/` runner must throttle across its 20-30 questions to
stay under the cap. Local embeddings have no cap, so retrieval never hits this.
This resolved the earlier open item about picking the embedding model (now
local BGE). We updated `CLAUDE.md` with all of the above. No errors this session.

---

## Decision 6 — Corpus: 15 finance-sector companies, and its effect on Step 4

**Date:** 2026-08-13

We fixed the domain to banking and finance and picked 15 large, well-known US
filers, spread across sub-sectors: money-center banks (JPMorgan Chase, Bank of
America), investment banks (Goldman Sachs, Morgan Stanley), regional banks (U.S.
Bancorp, PNC), consumer finance (Capital One, American Express), payment
networks (Visa, Mastercard), asset management (BlackRock), brokerage (Charles
Schwab), and insurers (MetLife, Travelers, Chubb). With one 10-K plus one or two
recent 10-Qs each, the corpus is about 30 to 45 documents, which stays under the
50-doc guidance and makes a real POC.

We found a real consequence for Step 4. The example ontology metrics
(`current_ratio`, `gross_margin`) do not apply to banks or insurers. Banks use an
unclassified balance sheet with no current assets or current liabilities line,
and gross margin is meaningless for a lender. So the finance corpus needs
sector-appropriate metrics. We decided to start with a common set that works
across all 15 (ROE, ROA, revenue growth, debt-to-equity) to keep Step 5 small,
and to add sub-sector metrics later (net interest margin and efficiency ratio for
banks, combined ratio and loss ratio for insurers). The CIKs in the company list
are best-effort and must be confirmed on EDGAR before download. No errors this
session, but this is a trap avoided: picking bank names without changing the
ontology would produce numbers that do not fit the formulas.

---

## Decision 7 — Ingest built; Docling failed on SEC HTML, bs4 became primary

**Date:** 2026-08-13

We implemented the `ingest/` module (steps 1 + 2) and ran it end to end. Step 1
resolved all 15 CIKs live from `company_tickers.json`, downloaded 45 filings (1
10-K + 2 10-Qs each) plus a companyfacts JSON per company, and wrote
`ingest/manifest.jsonl`. Step 2 chunked the 45 filings into 9,992 chunks in
`ingest/chunks.jsonl`, 95 percent with a real `section_id`.

**Tooling.** We put `pyproject.toml` at the repo root, not in `ingest/`, so one
shared venv serves all folders and `python -m ingest.run` resolves the package.
We used `uv` to pin Python 3.12 (system Python is 3.14, too new for torch).

**The main finding (error we hit and worked around).** The plan chose Docling as
the HTML parser. On real SEC iXBRL filings Docling failed three ways: it took
about 1 minute 47 seconds for one file (about 80 minutes for 45), it extracted
no section headings (so `section_id` would be null, which breaks the citation
anchor), and it mangled the financial tables into gibberish. The plan already
named a fallback for exactly this case, so we switched the fallback to primary: a
bs4 + lxml parser that strips the HTML to text, detects SEC headings (`Item N`,
`PART`, and ALL-CAPS statement titles), and packs the text into ~512-token
chunks. It runs in seconds and produces clean prose. The deterministic numbers
come from the XBRL companyfacts data, not from chunk text, so the chunk's job is
only to locate human-readable context.

**Other choices.** CIK resolution corrected BLK to `0002012383` (Decision 6 had
`0001364742`). `page` is null for HTML filings; `section_id` plus `char_start` /
`char_end` are the citation anchor. `token_count` is a word-based estimate, not a
real tokenizer count. Docling stays in `pyproject.toml` for possible future
PDF-only filings, but nothing uses it now — drop it if no PDFs appear. All SEC
I/O is stdlib `urllib`, throttled under 10 requests per second.

---

## Decision 8 — Removed Docling and its model cache

**Date:** 2026-08-13

Decision 7 kept Docling in `pyproject.toml` for possible future PDF filings. We
now removed it fully, because nothing uses it and it was heavy. `uv remove
docling` plus `uv sync` shrank the venv from 5.2 GB to 14 MB (Docling pulled
torch, torchvision, and transformers). We deleted the two Docling model
directories from the Hugging Face cache (`docling-layout-heron` and
`docling-models`), about 506 MB. Total reclaimed is about 5.7 GB. `beautifulsoup4`
and `lxml` stay as explicit dependencies, so the ingest chunker is unaffected.

We left three unrelated models in the Hugging Face cache: `bge-base-en-v1.5`
(2026-08-05) and `Qwen2.5-0.5B-Instruct` (2026-07-24) predate this project, and
`all-MiniLM-L6-v2` (2026-08-07) is a generic model that another project may use.
To re-add Docling later, put it back in `pyproject.toml` and run `uv sync`.
**Note:** the retrieval step (step 3) will reinstall torch through
`sentence-transformers` for the `bge-large-en-v1.5` embeddings — that is expected,
not a regression.

---

## Decision 9 — Retrieval runs on fastembed (no torch) with embedded Qdrant

**Date:** 2026-08-13

We built the `retrieval/` module (step 3) and made two choices that override the
letter of Decision 5 and the torch note at the end of Decision 8.

**fastembed, not sentence-transformers.** Decision 5 named `sentence-transformers`
for the `bge-large-en-v1.5` embeddings, and Decision 8 expected step 3 to reinstall
torch because of it. We used `fastembed` instead. It runs the same
`bge-large-en-v1.5` weights (dense) and `Qdrant/bm25` (sparse) on ONNX Runtime, so
no torch comes back and Decision 8's 5.7 GB reclaim stays intact. One dependency,
`qdrant-client[fastembed]`, covers both the client and both models. The Qdrant
client runs the models inline through `models.Document`, so the code never calls an
encoder by hand.

**Embedded Qdrant, not a Docker server.** The step-3 research recommended a pinned
`qdrant/qdrant:v1.16.0` container. We used the embedded client,
`QdrantClient(path="retrieval/qdrant_data")`, which runs in-process, persists to
disk, and exposes the same hybrid Query API (prefetch + RRF fusion). For a
~10,000-chunk portfolio project this removes a service to run and keep alive. The
client code is identical, so switching to a server later is a one-line change.

**Unchanged from the research.** Dense `bge-large-en-v1.5` at 1024-dim, cosine.
Sparse BM25 with the IDF modifier (load-bearing — it weights rare tickers and line
items). Prefetch 40 per side, RRF fusion at the k=60 default, top 20 returned. The
whole chunk record rides along as the point payload, so `doc_id`, `section_id`, and
`line_item` reach the citation step untouched. The cross-encoder reranker stays
optional and unbuilt.

---

## Decision 10 — Embedding model dropped to bge-base; corpus embedded on Colab GPU

**Date:** 2026-08-14

Decision 9 (and before it Decisions 3 and 5) chose `bge-large-en-v1.5` at 1024-dim
for the dense embeddings. We went forward with that. It is no longer possible on
this hardware, so we changed the model. This entry records the change. Decision 9
stays as written — it is the reasoning we had at the time.

**What happened.** The build machine is a WSL2 VM with 2 CPU cores and 1.9 GB RAM.
The 1.3 GB bge-large model did not fit. Loading it forced swap thrash, embedding ran
at about 2.8 seconds per chunk (roughly a 7-hour estimate for 9,992 chunks), and the
whole VM crashed more than once with out-of-memory.

**The path we walked.** We first tried the biggest model (bge-large, 1024-dim) —
too big, it crashed the VM. We then dropped to the smallest (bge-small, 384-dim) —
it fit, but 2 weak cores still made a local build very slow. We settled in the
middle on `bge-base-en-v1.5` (768-dim, about 440 MB). Two reasons for the middle
choice: bge-base is a quality step up from small, and the local VM must still load
the dense model at query time — bge-large would out-of-memory even on a single
query, while bge-base loads inside the 1.9 GB budget.

**Corpus embedding moved to Colab GPU.** Because 2 cores cannot embed 9,992 chunks
in reasonable time, the heavy embedding no longer runs on the local machine.
`colab_build_index.py` (repo root) embeds all chunks on a Colab GPU in minutes and
produces the `qdrant_data/` directory. We download it, unzip it into `retrieval/`,
and the local machine only embeds one query string per search — never the corpus.
The Colab script uses `sentence-transformers` on the GPU for the dense vectors
(Colab torch + CUDA works out of the box, unlike ONNX GPU), and `fastembed` for the
BM25 sparse vectors. The vectors are the same bge-base weights, unit-normalized, so
the local `fastembed` query path reads the index back correctly.

**What changed in code.** Only the model name and dense size in
`retrieval/config.py` (`bge-base-en-v1.5`, 768). The hybrid design, IDF sparse,
RRF k=60, prefetch 40, top 20, and payload passthrough from Decision 9 are all
unchanged. Verified: 9,992 points indexed, and distinct queries return distinct,
on-target, cited chunks. On a machine with more RAM and cores, raise `DENSE_MODEL`
back toward bge-large (rebuild on Colab, match the size). Any lost recall is what
the optional reranker recovers.

---

## Decision 11 — tools built: cross-sector 4, data-layer pulls, revenue fallback

**Date:** 2026-08-17

We built the `tools/` module (steps 4 + 5) and ran it end to end. `metrics.yaml`
(ontology) plus `facts.py` (data layer), `metrics.py` (functions + tool specs),
and `run.py` (self-checks). Verified: all 4 metrics compute for JPM and GS, each
number carries a full citation, and the self-checks pass offline.

**Metric set = the 4 cross-sector metrics** (roe, roa, debt_to_equity,
revenue_growth), per Decision 6. We dropped `current_ratio` and `gross_margin`
from the step-4 research examples. They do not apply to a finance corpus: banks
have no `us-gaap:AssetsCurrent` (confirmed missing for JPM), and gross margin is
meaningless for a lender. Tools built on those tags would error on every filing.

**Data-layer architecture (overrides the step-5 pseudocode).** The step-5 report
sketched tools that take raw numbers as inputs (Claude fills them). We did not do
that. A tool takes only `ticker` + `fiscal_year`. The deterministic `facts.py`
reads each number AND its citation straight from the companyfacts JSON in
`data/corpus/`. Claude never handles a raw number. Reason: CLAUDE.md's hard rule
(no number reaches the answer without a source) and the fact that Claude cannot
know which XBRL tag a company uses. The citation is the fact's own fields —
`accn` (accession), `form`, `fy`, `end`, plus the XBRL tag as `line_item` and
`doc_id = TICKER-FORM-FYYYYY`. `page` is null for HTML filings (Decision 7).

**Revenue needs a fallback tag list.** GS reports `us-gaap:RevenuesNetOfInterestExpense`,
not `us-gaap:Revenues` (14/15 filers use `Revenues`). So `source_concept` maps
each input to a LIST of candidate tags, tried in order. The data layer picks the
first present tag — one uniform rule, no per-company branching. This is another
reason the data layer, not Claude, owns tag selection.

**Period-selection rule.** companyfacts holds the full filing history, so a prior
year the local HTML corpus never downloaded still resolves (revenue_growth pulls
FY-1 from a separate accession). Within one fiscal year a filing lists the
current figure and a prior-year comparative under the same `fy`; the current one
has the later period end, so the loader picks `max(end)`. This is the one thing
easy to get wrong — a self-check pins JPM FY2025 equity to a known value.

**Dependencies and scope.** Added `pyyaml` for the ontology file. The three
ratios share one generic `_ratio` function driven by the ontology `inputs` order;
`revenue_growth` is its own function. `tool_specs()` builds the Claude tool
schema from `metrics.yaml`, so the schema never drifts from the formulas. The
`tools/` layer stays provider-agnostic — no langchain import. Binding to the LLM
with forced `tool_choice` belongs to `pipeline/`. Sub-sector metrics (net
interest margin, efficiency ratio, combined ratio) stay deferred per Decision 6.

---

## Decision 12 — added current_ratio back (per-company availability), kept gross_margin out

**Date:** 2026-08-17

This revisits the metric-set choice in Decision 11, which dropped both
`current_ratio` and `gross_margin`. We added `current_ratio` back. Decision 11
stays as written — it was the reasoning at the time.

**Why the change.** The graceful "not available" path already exists: a missing
tag makes `facts.get_fact` raise, and the metric function returns
`{is_error: True, ...}`. So a metric that applies to some filers but not others
is safe to ship — the companies that report the tag compute it, the rest get a
clear message. We reworded the error to read "… metric not available for this
company", naming the missing tag.

**What the data shows (checked across all 15).**
- `AssetsCurrent` / `LiabilitiesCurrent`: only **V and MA** (the payment
  networks) report them. The banks and insurers use an unclassified balance
  sheet, so they have no current-asset line. `current_ratio` computes for V and
  MA (V FY2025 = 1.08, cited) and returns "not available" for the other 13.
- `GrossProfit`, `CostOfGoodsSold`, `CostOfRevenue`: **no filer** reports any of
  them. So `gross_margin` cannot be computed for a single company in this corpus,
  even with the cost-based derivation the step-4 research suggested. A tool that
  can never succeed is dead weight, so `gross_margin` stays out until the corpus
  includes a filer that tags a cost line.

The metric set is now 5: `current_ratio`, `roe`, `roa`, `debt_to_equity`,
`revenue_growth`. No new code path — `current_ratio` reuses the generic `_ratio`
function. A self-check pins the V-works / JPM-not-available behavior.

---

## Decision 13 — XBRL tag migration: fallback lists per input, not one tag

**Date:** 2026-08-17

Adding `current_ratio` (Decision 12) surfaced a correctness bug that also hit the
original 4 metrics. Testing V (Visa) showed `roe`, `debt_to_equity`, and
`revenue_growth` returning "not available" — but V does report all of them. It
had migrated to different US-GAAP tags. The tool was falsely reporting a gap
where the data existed. That is the exact failure this project must not make, so
we treated it as a real bug, not a corpus limit.

**Root cause.** Filers change which XBRL concept they tag the same line to, and
different sub-sectors tag the same idea differently. A single tag per input is
wrong. We swept all 15 filers at their latest fiscal year and set a fallback list
per input, ordered so the first present tag is the correct one:

- **Net income** (`roe`, `roa` numerator):
  `[NetIncomeLoss, ProfitLoss]`. PNC and MA tag `ProfitLoss` (net income incl.
  noncontrolling interest), not `NetIncomeLoss`. `NetIncomeLoss` (parent) stays
  first — the standard ROE numerator.
- **Stockholders equity** (`roe`, `debt_to_equity` denominator):
  `[StockholdersEquity, StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest]`.
  V tags only the including-NCI variant. Parent equity stays first (convention).
- **Revenue** (`revenue_growth`):
  `[Revenues, RevenuesNetOfInterestExpense, RevenueFromContractWithCustomerExcludingAssessedTax]`.
  Order is load-bearing: `RevenueFromContractWithCustomer` is a sub-component for
  AXP/COF/MET (AXP: 41.3B component vs 72.2B top line) but the only revenue tag
  for BLK and V. Putting it last means the top-line tag wins when present, so all
  15 get the correct total.

**Result.** All 5 metrics now resolve for all 15 filers, except `current_ratio`
for the 13 banks and insurers — that "not available" is correct, they have no
classified balance sheet (Decision 12). No code changed; the fix is only the
fallback lists in `metrics.yaml`, because the data layer already tries candidates
in order. Self-checks pin the load-bearing picks: V equity via the NCI variant, V
revenue via `RevenueFromContractWithCustomer`, PNC net income via `ProfitLoss`,
and AXP revenue via the top-line tag (value 72.2B), not the component.

**Small inconsistency accepted.** For PNC/MA the numerator becomes `ProfitLoss`
(incl. NCI) while the equity denominator is parent `StockholdersEquity`, and for
V the reverse. The NCI amounts are tiny for these filers, and every number is
cited with its exact tag, so a reader sees precisely what was used. Revisit only
if an eval question needs strict parent-level consistency.

---

## Open items

- **Known limitation (ingest step 2): tables are split.** The bs4 chunker
  flattens HTML tables to text and cuts at the ~512-token budget, so a long table
  breaks across chunks. This deviates from the step-2 rule "do not split a table."
  It is tolerable because cited numbers come from the XBRL companyfacts JSON, not
  chunk text — a split table never corrupts a cited number. The cost is retrieval
  quality only. Fix (deferred, ~20-30 lines): walk the DOM, keep each `<table>`
  as one atomic block (allowed to exceed 512 tokens), and drop the iXBRL hidden
  header metadata that fills early chunks. Do this only if retrieval tuning shows
  it matters.


- Confirm the Apple FY2023 current-ratio answer key against the real filing on
  EDGAR before you lock it. The step 8 example shows the shape, not the last
  digits.
- Decide the reranker: optional in step 3. Skipped at the start (Decision 9). Add
  later as a post-step in `search.py` without changing the retrieval layer.

---

## Recommendations carried over from the research (for quick reference)

| Step | Recommendation |
|------|----------------|
| 1 | SEC EDGAR 10-K/10-Q + XBRL, ~10-20 docs in one folder. User-Agent header, 10 req/s cap. |
| 2 | Docling parser + its chunker. 512-token chunks, ~64-token overlap. Keep page + section id. |
| 3 | Qdrant native hybrid (sparse BM25 + dense) with RRF (k=60). bge-large-en-v1.5. top-k 40 -> 20. |
| 4 | Flat YAML metric dictionary. Borrow US-GAAP tag names (e.g. `us-gaap:AssetsCurrent`). |
| 5 | One function per formula. Force the call with `tool_choice`. Unit-test each function alone. |
| 6 | System-prompt plan-then-execute + a stop-and-ask ambiguity clause. LangGraph `interrupt()` later. |
| 7 | Custom citation trace for computed numbers. Native Claude Citations for free-text claims. |
| 8 | Plain JSONL answer key + a small stdlib runner. Pass = number in tolerance AND citation matches. |

---

## Decision 14 -- LangGraph as the agent framework

**Date:** 2026-08-17

**Decision.** Use LangGraph as the agent framework for `pipeline/`. Build the
request handler as a `StateGraph` with four nodes: retrieve, plan, tools,
fmt_node. Use LangGraph `interrupt()` for the stop-and-ask escalation so the
pause is a hard, unskippable graph state, not a soft prompt rule. Use LangChain
for model wrappers (`bind_tools`).

**Why.** Decision 3 already chose LangGraph. `interrupt()` gives a real pause
that the model cannot skip. The node structure maps cleanly to steps 6 and 7.
Graph state lets eval (step 8) inspect each node's output. LangGraph is a
relevant portfolio skill to demonstrate.

**Alternatives considered.**
- LangChain-only (no graph): no hard stop for ambiguity; the model can ignore
  "stop and ask" in a prompt. Rejected.
- Direct SDK calls: you write tool-call parsing and provider switching from
  scratch. More code, same result, no graph state. Rejected.

---

## Decision 15 -- LangChain provider packages

**Date:** 2026-08-17

**Decision.** Add `langchain-google-genai` (Google AI Studio, GEMINI_API_KEY)
and `langchain-anthropic` (Anthropic, ANTHROPIC_API_KEY). One LangChain chat-
model factory in `pipeline/config.py` reads the `LLM_PROVIDER` env var and
returns the right model. The rest of the graph never knows which provider is
active.

**Why google-genai, not google-vertexai.** Vertex AI requires a GCP project and
service-account auth. Google AI Studio (genai) needs only an API key and has a
free tier. This matches Decision 5's free-first philosophy.

---

## Decision 16 -- Gemini model: gemini-2.0-flash-latest alias

**Date:** 2026-08-17

**Decision.** Use the `gemini-2.0-flash-latest` alias, not a pinned version.
This alias always resolves to the current latest stable Flash model. Flash-class
models have generous free-tier limits (15 RPM, 1500 RPD), which comfortably
covers the eval runner's 20-30 questions.

**Why alias over pinned.** The pipeline improves automatically when Google rolls
the alias forward. No code change needed. Pinning a version (e.g.
`gemini-2.0-flash`) would require a manual bump each time.

---

## Decision 17 -- Claude model: claude-sonnet-4-20250514

**Date:** 2026-08-17

**Decision.** Use `claude-sonnet-4-20250514` for the opt-in Claude path.

**Why.** Best capability/cost ratio. The key is scarce (Decision 5), so cost
matters. Sonnet 4 supports forced `tool_choice` and extended thinking. The
pipeline's tasks (plan + structured tool call + format) do not need Opus-level
reasoning. ANTHROPIC_API_KEY is wired in `config.py` but untested until the key
is available.

---

## Decision 18 -- Ambiguity escalation: LangGraph interrupt()

**Date:** 2026-08-17

**Decision.** The planning node detects ambiguity by a heuristic: if the LLM
response contains no tool calls AND ends with "?", it calls `interrupt()`. The
caller (`run_question`) catches the pause, gets the user's answer via the
`Session` abstraction, and resumes with `Command(resume=answer)`. Checkpointer
is `MemorySaver` (in-process).

**Why interrupt() over prompt-only.** A prompt rule is soft; the model can
ignore it. `interrupt()` is a real graph pause -- the graph literally cannot
continue without the user's answer. This matches the project's core principle:
do not guess.

**Session abstraction.** `pipeline/session.py` defines an abstract `Session`
base class with one method: `ask(question) -> str`. `TerminalSession` reads
stdin. `ScriptedSession` returns pre-set answers for tests. A future web server
replaces `TerminalSession` without touching `graph.py`.

---

## Decision 19 -- Citation strategy: custom trace only

**Date:** 2026-08-17

**Decision.** Use only the custom citation trace (doc_id, line_item, formula,
inputs_with_sources). Do not use native Claude Citations for now.

**Why.** The custom trace works on both Gemini and Claude. Computed numbers
(tool results) cannot be cited via native Citations anyway -- that API only cites
document text. Native Citations also conflicts with structured outputs (returns
400 if both are enabled). The custom trace, not a provider feature, is the
source of truth for provenance. Native Citations can be added later for
qualitative free-text claims if needed.

---

## Decision 20 -- Answer output format: structured + rendered

**Date:** 2026-08-17

**Decision.** `pipeline/format.py` returns an `AnswerPayload` dict with two
views: (a) `answer_text` -- rendered inline-bracket text for the terminal; (b)
`numbers` -- a flat list of `NumberTrace` dicts (id, value, unit, doc_id,
line_item, formula, inputs_with_sources, citation). Eval (step 8) parses the
structured `numbers` list. The terminal user reads `answer_text`.

**NumberTrace structure.** A raw XBRL value has formula=None and
inputs_with_sources=[]. A derived metric has formula set and
inputs_with_sources listing the ids of its input NumberTraces. This makes a
derived number checkable down to its parts.

**Validator.** `validate_citations(payload)` asserts every raw value has doc_id
+ line_item, and every derived value lists its inputs_with_sources. It logs
warnings but does not raise -- a citation gap is a quality issue, not a crash.

---

## Decision 21 -- Retrieval integration: always search

**Date:** 2026-08-17

**Decision.** Retrieval runs as a fixed first step for every question. The top
10 chunks are passed as context to the planning LLM. The LLM does not decide
whether to search.

**Why.** Retrieval hits provide qualitative context (risk factors, MD&A) that
enriches answers beyond the bare metric number. Embedded Qdrant search is fast
(milliseconds). Making retrieval conditional adds a branch that the LLM might
skip when context would actually help. Simpler graph: retrieve is always step 1.

---

## Decision 22 -- python-dotenv for key management

**Date:** 2026-08-17

**Decision.** Added `python-dotenv` to dependencies. `pipeline/config.py`
auto-loads `.env` from the repo root at import time. `.env` is in `.gitignore`.
The `.env` file holds `GEMINI_API_KEY` (and optionally `ANTHROPIC_API_KEY`).
`LLM_PROVIDER` can be set there too.

**Why.** Avoids passing the key on every command line. The key lives in one
place (repo root `.env`), not in a shell profile. The `config.py` load is
transparent -- all other code and tests work unchanged.

---

## Decision 23 -- Chunk payload has None fields (not missing)

**Date:** 2026-08-17

**Observation (not a change).** The Qdrant chunk payload stores `section_id`,
`page`, and `line_item` as explicit `null` (Python `None`), not as missing keys.
`dict.get("section_id", "?")` returns `None` for an explicit null, not the
fallback "?". All code that reads chunk payload fields now uses `or "?"` and
`or ""` coercion instead of a `.get()` default. This is a defensive pattern
applied in `graph.py` (`_chunks_context`) and `format.py` (`render_answer`).

This is consistent with Decision 7: `page` is null for HTML filings. The XBRL
`section_id` is null for chunks that did not match a section heading heuristic.
Both are correct and expected. Citation anchors for these chunks use
`char_start`/`char_end` + `doc_id` instead.
