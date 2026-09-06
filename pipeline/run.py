"""pipeline/run.py — CLI entry point and self-checks.

Usage
-----
uv run python -m pipeline.run                        # self-checks (no LLM call)
uv run python -m pipeline.run "What is JPM ROE for FY2025?"
uv run python -m pipeline.run "What is the margin?"  # triggers ambiguity
uv run python -m pipeline.run --provider claude "..."

Self-checks (no API key needed)
--------------------------------
- config imports cleanly.
- format.py renders and validates a synthetic tool result.
- graph builds without error.
- session.ScriptedSession returns scripted answers.
"""

import argparse
import logging
import sys

import logconf
from pipeline import config as cfg
from pipeline import format as fmt
from pipeline import graph as g
from pipeline.session import ScriptedSession, TerminalSession

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Self-checks (offline)
# ---------------------------------------------------------------------------

def _self_checks() -> None:
    """Assert-based self-checks. All run without an API key."""

    # 1. Config imports cleanly and SYSTEM_PROMPT is non-empty.
    assert cfg.SYSTEM_PROMPT, "SYSTEM_PROMPT is empty"
    assert "STEP 1" in cfg.SYSTEM_PROMPT, "SYSTEM_PROMPT missing STEP 1"
    assert "STEP 2" in cfg.SYSTEM_PROMPT, "SYSTEM_PROMPT missing STEP 2"
    assert cfg.GEMINI_MODEL and "flash" in cfg.GEMINI_MODEL, cfg.GEMINI_MODEL

    # 2. format.py: build trace from a synthetic tool result.
    synthetic = {
        "metric": "roe",
        "value": 0.1234,
        "unit": "ratio",
        "formula": "net_income / stockholders_equity",
        "inputs": [
            {"name": "net_income", "value": 10_000_000, "citation": {
                "doc_id": "JPM-10K-FY2025", "line_item": "NetIncomeLoss",
                "tag": "us-gaap:NetIncomeLoss", "end": "2025-12-31",
                "accn": "0000123456-25-000001",
            }},
            {"name": "stockholders_equity", "value": 81_000_000, "citation": {
                "doc_id": "JPM-10K-FY2025", "line_item": "StockholdersEquity",
                "tag": "us-gaap:StockholdersEquity", "end": "2025-12-31",
                "accn": "0000123456-25-000001",
            }},
        ],
    }
    payload = fmt.format_answer(
        question="What is JPM's ROE?",
        plan="1. Compute ROE for JPM FY2025 using the roe tool.",
        tool_results=[synthetic],
        chunks=[],
    )
    assert payload["answer_text"], "answer_text is empty"
    assert len(payload["numbers"]) == 3, (
        f"expected 3 NumberTrace entries (2 inputs + 1 derived), got {len(payload['numbers'])}"
    )
    errors = fmt.validate_citations(payload)
    assert not errors, f"citation validation errors: {errors}"

    # 3. Error result does not add traces.
    err_result = {"metric": "current_ratio", "is_error": True, "error": "not available"}
    trace = fmt.build_trace([err_result])
    assert trace == [], f"expected empty trace for error result, got {trace}"

    # 4. Graph builds without an API key.
    graph = g.build_graph()
    assert graph is not None, "graph is None"

    # 5. ScriptedSession returns answers in order.
    sess = ScriptedSession(["gross margin", "FY2025"])
    assert sess.ask("which margin?") == "gross margin"
    assert sess.ask("which year?") == "FY2025"

    print("self-check: ok")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logconf.setup_logging()

    parser = argparse.ArgumentParser(
        description="pipeline/ CLI -- run a financial question through the full pipeline."
    )
    parser.add_argument("question", nargs="?", help="Question to ask. Omit to run self-checks.")
    parser.add_argument(
        "--provider", choices=["gemini", "claude"], default=None,
        help="LLM provider. Default: read LLM_PROVIDER env var (fallback: gemini)."
    )
    parser.add_argument(
        "--thread", default=cfg.DEFAULT_THREAD_ID,
        help="LangGraph thread ID (for resume after interrupt)."
    )
    args = parser.parse_args()

    if args.question is None:
        _self_checks()
        return

    # Override provider env var if flag given.
    if args.provider:
        import os
        os.environ["LLM_PROVIDER"] = args.provider

    # Force the LLM factory to pick up the (possibly updated) provider.
    cfg.get_llm.cache_clear()

    session = TerminalSession()

    print(f"\nProvider : {(args.provider or 'gemini').upper()}")
    print(f"Question : {args.question}")
    print("-" * 60)

    answer = g.run_question(
        question=args.question,
        session=session,
        thread_id=args.thread,
    )

    if not answer:
        print("No answer produced. Check logs/verify_ai.log for details.")
        sys.exit(1)

    print()
    print(answer.get("answer_text", "(no rendered answer)"))


if __name__ == "__main__":
    main()
