"""pipeline/format.py -- citation trace builder, answer renderer, validator.

Step 7: every number in the answer carries a citation trace.
"""

import logging

log = logging.getLogger(__name__)

CHUNKS_IN_PAYLOAD = 5

METRIC_LABELS = {
    "roe": "Return on Equity",
    "roa": "Return on Assets",
    "current_ratio": "Current Ratio",
    "debt_to_equity": "Debt-to-Equity",
    "revenue_growth": "Revenue Growth",
}

METRIC_AS_PCT = {"roe", "roa", "revenue_growth"}


def _fmt_metric_value(value, metric_name):
    if metric_name in METRIC_AS_PCT:
        return f"{value * 100:.2f}%"
    return f"{value:.4f}x"


def _fmt_input_value(value):
    if abs(value) >= 1e9:
        return f"${value / 1e9:,.2f}B"
    if abs(value) >= 1e6:
        return f"${value / 1e6:,.2f}M"
    return f"${value:,.0f}"


def _trace_from_tool_result(result, idx):
    """Convert one tool result into NumberTrace list entries."""
    if result.get("is_error"):
        return []

    traces = []
    input_ids = []

    for inp in result.get("inputs", []):
        cit = inp["citation"]
        nid = "n" + str(idx) + "_" + inp["name"]
        input_ids.append(nid)
        traces.append({
            "id": nid,
            "value": inp["value"],
            "unit": result.get("unit", ""),
            "doc_id": cit.get("doc_id", ""),
            "line_item": cit.get("line_item", ""),
            "formula": None,
            "inputs_with_sources": [],
            "citation": cit,
        })

    metric_id = "n" + str(idx) + "_" + result["metric"]
    traces.append({
        "id": metric_id,
        "value": result["value"],
        "unit": result.get("unit", ""),
        "doc_id": traces[0]["doc_id"] if traces else "",
        "line_item": result["metric"],
        "formula": result.get("formula", ""),
        "inputs_with_sources": input_ids,
        "citation": None,
    })
    return traces


def build_trace(tool_results):
    """Build the full NumberTrace list from all tool results."""
    traces = []
    for i, res in enumerate(tool_results):
        traces.extend(_trace_from_tool_result(res, i))
    return traces


def _format_one_result_md(res):
    """Render one metric result as a markdown section."""
    metric = res["metric"]
    label = METRIC_LABELS.get(metric, metric.replace("_", " ").title())

    if res.get("is_error"):
        doc_id = ""
        inputs = res.get("inputs", [])
        if inputs:
            doc_id = inputs[0].get("citation", {}).get("doc_id", "")
        ticker = doc_id.split("-")[0] if doc_id else "?"
        return f"## {label} — {ticker}\n\n**Not available.** {res['error']}\n"

    value = res["value"]
    inputs = res.get("inputs", [])
    first_cit = inputs[0]["citation"] if inputs else {}
    doc_id = first_cit.get("doc_id", "?")
    ticker = doc_id.split("-")[0] if "-" in doc_id else doc_id
    fiscal_year = doc_id.split("FY")[-1] if "FY" in doc_id else "?"

    display = _fmt_metric_value(value, metric)
    lines = [f"## {label} — {ticker} (FY{fiscal_year})", "", f"**{display}**", ""]

    if inputs:
        lines.append("| Input | Value | Source |")
        lines.append("|-------|-------|--------|")
        for inp in inputs:
            cit = inp["citation"]
            tag = cit.get("tag", cit.get("line_item", "?"))
            src_doc = cit.get("doc_id", "?")
            lines.append(f"| {inp['name']} | {_fmt_input_value(inp['value'])} | {src_doc} · {tag} |")
        lines.append("")

    formula = res.get("formula", "")
    if formula:
        lines.append(f"*{formula}*")

    return "\n".join(lines)


def render_answer(question, plan, tool_results, chunks):
    """Render the full answer as markdown for display in the chat UI."""
    sections = []
    for res in tool_results:
        sections.append(_format_one_result_md(res))
    return "\n\n---\n\n".join(sections) if sections else "No results."


def format_answer(question, plan, tool_results, chunks):
    """Return AnswerPayload: structured trace + rendered text."""
    trace = build_trace(tool_results)
    text = render_answer(question, plan, tool_results, chunks)
    return {
        "answer_text": text,
        "numbers": trace,
        "plan": plan,
        "chunks_used": chunks[:CHUNKS_IN_PAYLOAD],
        "tool_results": tool_results,
    }


def validate_citations(payload):
    """Return list of validation errors. Empty = pass.

    Rule: every raw NumberTrace must have doc_id + line_item.
    Every derived NumberTrace must list inputs_with_sources.
    """
    errors = []
    id_set = {n["id"] for n in payload["numbers"]}

    for n in payload["numbers"]:
        if not n.get("formula"):
            if not n.get("doc_id"):
                errors.append(n["id"] + ": missing doc_id")
            if not n.get("line_item"):
                errors.append(n["id"] + ": missing line_item")
        else:
            for src_id in n.get("inputs_with_sources", []):
                if src_id not in id_set:
                    errors.append(n["id"] + ": input_source " + repr(src_id) + " not in trace")
            if not n.get("inputs_with_sources"):
                errors.append(n["id"] + ": derived but inputs_with_sources is empty")

    return errors
