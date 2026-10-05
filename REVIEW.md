# verify_ai: Critical Review

Review date: 2026-09-30. Scope: the whole repo, with focus on the agent and the agent workflow.

I read every Python file, `metrics.yaml`, `decisions.md` (Decisions 1 to 23), the READMEs, and `logs/verify_ai.log`. I also ran offline checks against the real corpus. I did not call any LLM. I did not review `frontend/index.html`, because the file was not readable from my session. The eval folder holds only a README, so I reviewed the plan for it, not the code.

## 1. Verdict

The deterministic core is good. The agent around it is thin, and it does not deliver the guarantees that the docs claim.

- The tools layer (`tools/facts.py`, `tools/metrics.py`, `tools/metrics.yaml`) is the best part of the project. The LLM passes only a ticker and a year. Code reads the number and its source. This design is correct.
- The agent is a router with a single job: pick a metric, a ticker, and a year. It does not plan in a useful way. Its plan text is thrown away. The final answer never uses the LLM output.
- The "hard stop on ambiguity" is a soft rule in disguise. The model decides whether the stop happens.
- The system has no test that measures if it works. The `eval/` folder is empty. Every claim in `CLAUDE.md` about citations is untested.
- The citation does not meet the project's own hard rule. The `page` field is always null. The validator only logs a warning.

The project is a working demo for the happy path. It is not yet a verifiable system.

## 2. What the system does (verified)

1. `retrieve` runs a hybrid search and returns 10 chunks (`pipeline/graph.py:119`).
2. `plan` sends the top 5 chunks (400 characters each) and the question to the LLM. The LLM has 5 tools bound (`graph.py:143`).
3. `tools` runs the tool calls. If the plan had no tool call, it forces one with `tool_choice="any"` (`graph.py:194`).
4. `fmt_node` renders markdown from the tool results only (`pipeline/format.py:122`). It ignores `plan` and `chunks`.

The graph is a straight line with no conditional edge (`graph.py:270`). The only branch is an `if` inside `node_plan`.

The five tools are `roe`, `roa`, `debt_to_equity`, `current_ratio`, and `revenue_growth`. Each reads annual 10-K facts from the SEC `companyfacts` JSON.

## 3. What works well

- **Data layer owns the numbers.** `facts.get_fact` returns the value with `accn`, `form`, `end`, and the XBRL tag. The LLM never sees a raw number. This is the right way to build it.
- **Tag fallback lists** in `metrics.yaml` (Decision 13). The ordering notes are careful and correct.
- **Ontology drives the tool schema.** `tool_specs()` builds the schema from the YAML, so the two cannot drift.
- **Error paths return data, not exceptions**, for the "tag missing" case.
- **Decisions log.** It records real reasons and real failures (Docling, OOM on bge-large). This is rare and useful.
- **Free-first provider design** and the `Session` abstraction are sound for a demo.

## 4. Critical findings (fix first)

### 4.1 The pipeline crashes on an unknown ticker (verified)

`node_tools` catches any exception and builds `{"is_error": True, "error": ...}` with no `metric` key (`graph.py:221-223`). `_format_one_result_md` then reads `res["metric"]` (`format.py:84`). This raises `KeyError`.

I ran this. `REGISTRY["roe"]("AAPL", 2025)` raises `FileNotFoundError`, because `load_facts` opens `AAPL_facts.json`. `_ratio` only catches `LookupError` (`metrics.py:57`). Then `render_answer` on the error result raises `KeyError: 'metric'`.

Failure scenario: a user asks about Apple. The LLM calls `roe(ticker="AAPL")`. The user gets an HTTP "error" status with a stack trace message. The right answer is "AAPL is not in the corpus. These 35 tickers are."

Fix:
- Put the ticker list in the tool schema as an enum (`Literal[...]`). Gemini and Claude both enforce it.
- Validate `fiscal_year` against the years present in the facts.
- Add the tool name to every error result in `node_tools`.

### 4.2 Forced tool call means the agent cannot say "I cannot answer" (design flaw)

When the plan step returns text with no tool call, `node_tools` calls the model with `tool_choice="any"` (`graph.py:194-198`). The model must call a tool. For a question outside the five metrics, it will pick the closest one and fill in arguments.

Failure scenarios:
- "Summarize JPM's risk factors." The model must call a metric tool. The user gets a ROE table.
- "What was Visa's gross margin?" `gross_margin` does not exist. The model may call `roe` and the answer looks valid, with a valid citation, for the wrong question.
- "What was JPM's net income?" There is no raw-fact tool. The user gets a ratio, not the number.

This is the worst kind of failure for this project. The output looks verified but answers a different question. The `CLAUDE.md` rule "force a tool call" was meant to stop free-text math. It was not meant to remove the refusal path.

Fix: add a router step with three outcomes. See section 7.

### 4.3 The interrupt is not a hard stop, and it runs the LLM twice (verified in logs)

Decision 14 and 18 say `interrupt()` is "a real graph pause the model cannot skip." This is only half true. The pause is real. But the model decides whether to reach it. The trigger is `not tool_calls and plan_text.endswith("?")` (`graph.py:162`). If the model calls a tool for an ambiguous question, no pause happens. If the model writes a question that does not end with "?", no pause happens either.

There are two more problems in the same code:

1. **The node re-runs from the top on resume.** LangGraph does this by design. `node_plan` makes its first LLM call before `interrupt()`. On resume, the first call runs again. `logs/verify_ai.log` shows this: two `plan: invoking LLM` lines and two `plan: ambiguous` lines for one question (2026-08-17 13:51:55 to 13:52:00). This doubles the cost of every clarification on a free tier with an RPM cap.
2. **Non-determinism can drop the answer.** `temperature=0` does not make Gemini deterministic. If the second first-call returns a tool call, `interrupt()` is never reached. The user's clarification is discarded, and the run continues on a guess.

After the resume, a second question from the model is not handled. The code calls the model once more. If it asks again with no tool call, `node_tools` forces a tool call (see 4.2). The system guesses, which the project says it must never do.

Fix: split into nodes. See section 7.

### 4.4 The citation does not meet the project's own hard rule

`CLAUDE.md` says: "Do not let a number reach the final answer without a `doc_id`, a `page`, and a `line_item`." The code does not do this.

- `page` is `None` on every number (`facts.py:68`). Decision 7 accepts this for HTML. The README still says the citation names "the page" and shows `page: 47`. That is false.
- `validate_citations` does not check `page`. It also does not block. It logs a warning and the answer is sent anyway (`graph.py:250-254`, Decision 20).
- The citation points to `companyfacts`, not to the filing text. A person cannot open the cited chunk. There is no `chunk_id`, no `char_start`, and no filing URL in the trace, even though `manifest.jsonl` holds `filing_url`.
- For `revenue_growth`, the prior-year `doc_id` is `TICKER-10-K-FY(N-1)`. That filing is not in the corpus or the index. The citation names a document the system does not hold.
- `doc_id` is built from `fiscal_year` in `facts.py:62`. The chunk `doc_id` is built from the report-date year in `ingest/download.py:116`. These agree for December filers. They can differ for other fiscal-year ends.

Fix (best option): the corpus is iXBRL. Every reported number in the HTML sits in an `<ix:nonFraction name="us-gaap:..." contextRef="...">` element. The chunker strips these tags (`ingest/chunk.py:52-56`). Keep them. Then for each fact, you can find the exact character offset in the exact filing. That gives a real locator: `accn`, tag, context, and `char_start`. It also lets the validator check that the number in `companyfacts` appears in the cited filing text. This turns "citation exists" into "citation is correct."

### 4.5 No eval exists, so no claim is measured

`eval/` holds one README. `decisions.md` calls eval "the point" of the isolation. Right now:

- No test checks that the right tool is chosen for a question.
- No test checks refusal, ambiguity, or multi-metric questions.
- No test would have caught 4.1 or the coverage gap in 5.1.

For an agent project this is the largest gap. Every change to the prompt or the model is a blind change. The eval set needs 30 to 50 questions. It needs four kinds: answerable (with expected number and expected citation), ambiguous (expects a clarification), out-of-scope (expects a refusal), and unknown entity (expects a "not in corpus").

## 5. Data and tools layer

### 5.1 Coverage broke when the corpus grew (verified)

Decision 13 says all five metrics resolve for all filers. The corpus is now 35 tickers (uncommitted change in `ingest/config.py`). I ran every metric for FY2025 on all 35:

- `revenue_growth` fails for `TFC`, `FITB`, and `RF`. These three banks use other revenue tags.
- `current_ratio` fails for 33 of 35. Only `V` and `MA` work. This tool is correct but almost dead.

No test caught this. There is no Decision 24 in `decisions.md`, although `ingest/config.py:13` cites it.

### 5.2 Metric definitions are simple and the tool text does not say so

- `roe` and `roa` use year-end equity and year-end assets. Most analysts use the average of the opening and closing balance. The tool description does not say "year-end." A user who compares the result with a data vendor will see a mismatch and lose trust.
- `roe` can use `ProfitLoss` (with non-controlling interest) over parent equity. Decision 13 accepts this. The trace shows the tag, but the rendered answer does not flag the mix.
- `debt_to_equity` is total liabilities over equity. For a bank this is a leverage ratio near 10 to 12. The name suggests borrowed debt. State the meaning in the tool description and in the rendered answer.
- Ratios use unrounded inputs but the value is rounded to 6 places before storage (`metrics.py:63`). That is fine. The display rounds to two places for percent. Keep both.

### 5.3 Only annual 10-K facts are supported

`facts.get_fact` defaults to `form="10-K"` and `fp == "FY"` (`facts.py:37,54`). The corpus holds two 10-Qs per company, including Q2 FY2026. The system indexes them but cannot compute anything from them. A question like "JPM ROE for the latest quarter" cannot work. The prompt says "most recent fiscal year in the corpus," and the model does not know what that year is.

Fix: make `fiscal_year` optional. Let the tool resolve "latest" from the facts file. Return the resolved year in the result. Do not ask the LLM to guess the current year.

### 5.4 One risk to check

`get_fact` picks `max(end)` among facts with the same `fy` (`facts.py:57`). If a filer tags a quarterly duration with `fp="FY"` in the same filing, two facts can share the same `end`. I found no case in the corpus, but I did not scan all tags. Add a duration check (start to end near 365 days) for income-statement facts. It is a cheap guard.

## 6. Retrieval and ingest

### 6.1 Retrieval costs seconds and the answer does not use it

Every question pays for a hybrid search, and the answer ignores the result:

- `render_answer` does not read `chunks` (`format.py:122`).
- The LLM sees 5 chunks cut to 400 characters (`graph.py:135-138`). That is about a fifth of one 512-token chunk. No tool takes chunk content as input.
- The log shows 17 to 28 seconds per search in August. The last search on the 21,966-point index shows about 2 minutes 49 seconds (2026-09-30 09:23 to 09:26). Part of that may be model load. Even so, it is a large cost for unused context.
- Qdrant local mode warns above 20,000 points (`Collection <filings> contains 21966 points`). You are now over the limit the library recommends.

Decision 21 says retrieval gives "qualitative context." No node turns it into an answer. Choose one:

1. Cut retrieval from the numeric path. Run it only for qualitative questions.
2. Build the qualitative path: retrieve, then answer from chunks with quoted spans and chunk citations. This is the better product.

### 6.2 Chunks lose the table structure

Known and accepted in the open items. Retrieval for numeric questions ("what was net interest income") will match flattened table text. This will hurt as soon as the qualitative path exists. The iXBRL fix in 4.4 also fixes this, because you can keep each table as one block.

### 6.3 Embedding and index

- The dense model is `bge-base`, chosen for a 1.9 GB VM. That is a hardware limit, not a quality decision. It is recorded in Decision 10. Fine for now.
- `retrieval/index.py:5` still says `bge-small`. `pyproject.toml` and the README say `bge-large`. Three different names for one model. The code in `config.py` is the truth. The docs are wrong.
- No filter is applied. A question about "GS" searches all 35 companies. Use a payload filter on `doc_id` or ticker once the router extracts the entity. Hybrid search over 22,000 chunks with no filter will mix companies.

## 7. Recommended agent redesign

The current graph is `retrieve -> plan -> tools -> fmt`. Replace it with a graph that has real branches. Keep the tools layer as it is.

```
classify  -> (structured output, one LLM call)
   |  intent: metric | lookup | qualitative | ambiguous | out_of_scope
   |  entities: tickers (validated), fiscal_year (optional), metrics
   v
route (conditional edge)
   ambiguous     -> clarify (interrupt only, no LLM call) -> classify
   out_of_scope  -> refuse (template text, no LLM)
   metric        -> compute (tools, no forced choice) -> fmt
   qualitative   -> retrieve (filtered) -> answer_with_quotes -> fmt
```

Why this shape:

1. **Structured output beats tool-call heuristics.** Use `with_structured_output` on a Pydantic model. `intent` is an enum. `tickers` is a list of enum values. `fiscal_year` is optional. Invalid output fails at the schema, not at `endswith("?")`.
2. **The interrupt node holds only the interrupt.** On resume LangGraph re-runs only that node. No LLM call is repeated. The clarification result is stored in state, and `classify` runs again with it.
3. **Refusal is a first-class outcome.** Fixes 4.2.
4. **Bound the loop.** Allow at most two clarification rounds. After that, refuse with the ambiguity stated. Never force a guess.
5. **Drop the plan text.** Nothing reads it. If you want a visible plan for the user, render it from the structured output. This removes one LLM call.
6. **Drop the post-tool LLM call.** In `node_tools`, the model is called after each tool result and its text is never used (`graph.py:233-234`). Compute all requested `(metric, ticker, year)` tuples from the structured output in plain Python. That is deterministic and cheaper. It also removes the failure where the model stops early or repeats a call.
7. **Verify after compute.** Add a `verify` node. It checks: every number has a locator (4.4), the tool result matches the intent (metric and ticker in the answer equal the metric and ticker asked), and the number appears in the cited filing text. If it fails, return a refusal with the reason.

This gives 1 LLM call for numeric questions, down from 3 to 4 today. On the Gemini free tier, this is the single biggest gain in throughput.

## 8. API and operations

### 8.1 Paused conversations get stuck after a restart

The checkpointer is `MemorySaver` (`graph.py:276`). The status `awaiting_clarification` is stored in SQLite (`api/runner.py:70`). After a server restart, the graph state is gone and the DB status stays. The next message calls `start_resume`, `graph.invoke(Command(resume=...))` runs on an empty thread, and the request ends in an error. Every later message repeats this. The user must delete the conversation.

The Makefile runs `uvicorn --reload`. Every file save restarts the server and triggers this state.

Fix: use `langgraph-checkpoint-sqlite` (`SqliteSaver`) in the same DB file. Also reset the status to `active` if a resume fails.

### 8.2 Other issues

- `_status` is an in-memory dict that never shrinks (`api/runner.py:15`). It also breaks with more than one worker. Store request state in SQLite or return the result from the POST.
- No conversation memory. Each turn starts with empty `messages` (`_initial_state`). "And for Goldman?" cannot work. The conversation id is the thread id, but the graph does not read earlier turns. Pass the last turn's resolved entities and metric into `classify`.
- `allow_origins=["*"]` and `--host 0.0.0.0` with no auth or rate limit (`api/main.py:38`, `Makefile`). Anyone on the network can spend your Gemini and Anthropic quota. Bind to `127.0.0.1` for local work. Add a simple token check before you share the URL.
- `StepTracker.on_chain_start` reads `serialized["name"]` (`api/runner.py:30`). Newer LangChain versions pass `serialized=None` and put the name in `kwargs["name"]`. If the progress label does not update, this is the reason. I did not run the UI to confirm.
- The unrelated `qdrant_data.zip` (114 MB) sits in the repo root. It is git-ignored. Move it out of the tree.

### 8.3 Observability claims are false

The README says `logfire.instrument_langchain()` traces LLM calls and graph nodes. In `api/main.py:18` that line is commented out with the note "removed: no longer in logfire API." So only FastAPI requests are traced. No LLM call, no node, no token count is traced. For an agent, this is the data you need most. Add tracing for the actual provider SDK (check the current Logfire docs for `instrument_google_genai` and `instrument_anthropic`) or use LangSmith for LangGraph. Log the tool name, arguments, and result per call.

## 9. Provider and model choices

- `GEMINI_MODEL = "gemini-3.5-flash"` in `pipeline/config.py:29`. Decision 16 says `gemini-2.0-flash-latest`. The comment in code says "alias." The name is a pinned version string, not an alias. Update Decision 16 with a new entry (do not edit the old one).
- `CLAUDE_MODEL = "claude-sonnet-4-20250514"`. The current Sonnet model is newer. Decision 17 notes the Claude path is "untested." An untested opt-in path is a liability. Forced tool use with Claude returns only a tool call, with no text before it. Your plan-then-call pattern relies on text plus a tool call in one reply. It works in auto mode and fails in forced mode. The redesign in section 7 removes this dependency.
- `CLAUDE.md` says to use adaptive thinking on Claude. Decision 17 says "extended thinking." The code sets neither. Pick one and write it down.
- Free-tier limits are quoted in Decision 16 (15 RPM, 1500 RPD). Check them against the current Google docs before you run the eval. Limits change often.

## 10. Documentation drift

| Where | Claim | Fact |
|-------|-------|------|
| `README.md` | 15 companies, 45 filings | 35 tickers, 105 manifest rows, 21,966 chunks |
| `README.md` | Citation has a `page` | `page` is always null |
| `README.md` | The chunker never splits a table | It does (open item in `decisions.md`) |
| `README.md` | `bge-large-en-v1.5` | `bge-base-en-v1.5` |
| `README.md` | Logfire traces LLM calls | The call is commented out |
| `ingest/config.py:13` | "Decision 24" | No such entry |
| `retrieval/index.py:5` | `bge-small` | `bge-base` |
| `CLAUDE.md` | Says `decisions.md` is read first | It is git-ignored and not in the repo |
| `CLAUDE.md` | Graph has an ambiguity check node | No such node. The check sits inside `node_plan`. |

`decisions.md`, `docs/`, and `eval/` are in `.gitignore`. If the disk fails, the reasoning and the eval set are lost. The eval set and the decision log are the assets that matter most. Track them.

## 11. Priority list

Do these in order.

1. **Fix the crash (4.1).** Ticker enum, year check, tool name in error results. About 30 lines.
2. **Build a small eval (4.5).** 30 questions, four kinds. A runner that checks the number, the tool choice, and the outcome type. Use a delay between calls for the free tier. Do this before the redesign so you can measure the change.
3. **Add refuse and ambiguity outcomes (4.2, 4.3).** Use structured output and the graph in section 7.
4. **Fix the citation (4.4).** Keep iXBRL tags in the chunker. Store a locator per fact. Make `validate_citations` block the answer when a number has no locator.
5. **Switch to `SqliteSaver` (8.1).** Reset the stuck status on failure.
6. **Fix the three failing revenue tags (5.1).** Add a coverage test that runs every metric on every ticker. It should fail the build when a ticker regresses.
7. **Decide the role of retrieval (6.1).** Either remove it from the numeric path or build the qualitative path.
8. **Close the network exposure (8.2).** Bind to localhost.
9. **Repair traces and docs (8.3, 10).** Add new decision entries. Do not edit old ones.

## 12. What I did not verify

- I did not run any LLM call. The claims about model behavior come from the code paths and from `logs/verify_ai.log`.
- I did not review `frontend/index.html`.
- I did not check the `max(end)` duration risk (5.4) across all tags.
- I did not run the Claude path.
- The timing numbers come from the log. They include time on a 2-core VM with 1.9 GB of RAM.
