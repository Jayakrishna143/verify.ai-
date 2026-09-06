"""pipeline/format.py -- citation trace builder, answer renderer, validator.

Step 7: every number in the answer carries a citation trace.
"""

import logging

log = logging.getLogger(__name__)

CHUNKS_IN_PAYLOAD = 5


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


def _format_one_result(res):
    """Render one metric result as a human-readable bullet."""
    if res.get("is_error"):
        return "  - " + res["metric"] + ": " + res["error"]

    value = res["value"]
    unit = res.get("unit", "")
    metric = res["metric"]

    if unit in ("ratio", "decimal"):
        display = "{:.4f}".format(value)
    elif unit == "%":
        display = "{:.2f}%".format(value * 100)
    else:
        display = "{:,.2f}".format(value)

    cit_parts = []
    for inp in res.get("inputs", []):
        cit = inp["citation"]
        doc = cit.get("doc_id", "?")
        period = cit.get("end", "?")
        tag = cit.get("tag", cit.get("line_item", "?"))
        cit_parts.append(doc + ", " + period + ", XBRL:" + tag)

    cit_str = " | ".join(cit_parts)
    formula = res.get("formula", "")
    formula_str = " (formula: " + formula + ")" if formula else ""

    line1 = "  - " + metric + ": " + display + formula_str
    line2 = "    [" + cit_str + "]"
    return line1 + "\n" + line2


def render_answer(question, plan, tool_results, chunks):
    """Render the full answer as inline-bracket text for terminal display."""
    lines = []
    lines.append("Question: " + question)
    lines.append("")
    lines.append("Plan:")
    lines.append(plan.strip())
    lines.append("")
    lines.append("Results:")
    for res in tool_results:
        lines.append(_format_one_result(res))
    if chunks:
        lines.append("")
        lines.append("Context: " + str(len(chunks)) + " filing chunks retrieved.")
        for c in chunks[:3]:
            doc = c.get("doc_id") or "?"
            sec = c.get("section_id") or "?"
            snippet = (c.get("text") or "")[:120].replace("\n", " ")
            lines.append("  [" + doc + " / " + sec + "] " + snippet + "...")
    return "\n".join(lines)


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
