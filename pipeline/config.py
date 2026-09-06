"""pipeline/config.py — LLM factory, system prompt, and environment wiring.

One factory function returns a LangChain chat model for the active provider.
The rest of the graph never knows which provider is live.

Providers
---------
gemini (default)  GEMINI_API_KEY required.  Model: gemini-2.0-flash-latest.
claude (opt-in)   ANTHROPIC_API_KEY required.  Model: claude-sonnet-4-20250514.

Select with LLM_PROVIDER env var. Missing key prints a clear error and exits.
"""

import logging
import os
import pathlib
from functools import lru_cache

from dotenv import load_dotenv

# Load .env from repo root automatically so 'uv run' picks up GEMINI_API_KEY
load_dotenv(pathlib.Path(__file__).resolve().parent.parent / '.env')

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model names
# ---------------------------------------------------------------------------
GEMINI_MODEL = "gemini-3.5-flash"        # alias -- always latest stable Flash (currently gemini-3.6)
CLAUDE_MODEL = "claude-sonnet-4-20250514"

# Retrieval: how many chunks to surface per question
RETRIEVAL_LIMIT = 10

# LangGraph thread config
DEFAULT_THREAD_ID = "verify-ai-session"

# ---------------------------------------------------------------------------
# System prompt (step 6: plan-then-execute + stop-and-ask rule)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a financial research assistant for SEC EDGAR filings (10-K, 10-Q, and XBRL data).

A separate deterministic system holds all the data, runs all math, and attaches a source citation to every number. You plan; the tools compute. You NEVER compute or invent a final number in free text.

## Default assumptions — use these silently, do not ask

- "most recent", "latest", or no year stated → use the most recent fiscal year in the corpus.
- "current year" or "this year" → most recent fiscal year.
- A company name that maps to exactly one ticker in the corpus → use that ticker.

## How you must answer

STEP 1 - Write a numbered plan first.
Before you call ANY tool, output a numbered plan in plain words. Each line is one action. State which metric you will compute, for which company and fiscal year, and which tool you will call.

STEP 2 - Ask ONLY when you cannot pick a reasonable default.
Interrupt with a clarifying question only when the question is genuinely unresolvable without the user's input. This means: the term has two or more valid metric interpretations and picking the wrong one would return a different number.

Ask when:
- "margin" with no qualifier — could be gross, operating, or net margin (three different numbers).
- "earnings" with no qualifier — could be net income or EPS (different units).
- "current" as a metric — could mean the current ratio or "the current period".
- A company name or ticker matches more than one filer in the corpus.

Do NOT ask about:
- Which fiscal year, if the question says "most recent" or omits the year — assume the latest in corpus.
- GAAP vs non-GAAP — always use GAAP (what the tools return from XBRL).
- Format preferences.
- Anything you can resolve with a safe, obvious default.

If the term is unambiguous (e.g. "gross margin for FY2024"), do NOT ask. Proceed to the plan.

STEP 3 - Call tools only after the plan is clear and unambiguous.
Use the available metric tools. Pass only ticker and fiscal_year — the tools pull each number and its citation automatically from XBRL data.

## Output format
- If genuinely ambiguous (cannot resolve): output ONLY the clarifying question. No plan. No tools.
- If clear (or resolved by default assumptions): output the numbered plan, then call the tools.
"""


@lru_cache(maxsize=1)
def get_llm(provider: str | None = None):
    """Return a LangChain chat model for the active provider.

    provider: 'gemini' (default) or 'claude'.
    Reads LLM_PROVIDER env var if provider is None.
    Raises SystemExit on a missing API key with a clear message.
    """
    resolved = (provider or os.environ.get("LLM_PROVIDER", "gemini")).lower().strip()

    if resolved == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise SystemExit(
                "ERROR: GEMINI_API_KEY (or GOOGLE_API_KEY) is not set.\n"
                "Export it or set LLM_PROVIDER=claude if you have an Anthropic key."
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        log.info("LLM provider: Gemini (%s)", GEMINI_MODEL)
        return ChatGoogleGenerativeAI(
            model=GEMINI_MODEL,
            google_api_key=key,
            temperature=0,
        )

    if resolved == "claude":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit(
                "ERROR: ANTHROPIC_API_KEY is not set.\n"
                "Export it or omit LLM_PROVIDER to use Gemini (free tier)."
            )
        from langchain_anthropic import ChatAnthropic
        log.info("LLM provider: Claude (%s)", CLAUDE_MODEL)
        return ChatAnthropic(
            model=CLAUDE_MODEL,
            api_key=key,
            temperature=0,
        )

    raise SystemExit(f"ERROR: Unknown LLM_PROVIDER '{resolved}'. Choose 'gemini' or 'claude'.")
