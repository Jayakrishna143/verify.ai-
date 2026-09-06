"""Step 5 — one deterministic function per formula, plus the tool specs Claude
sees.

A metric function takes only `ticker` + `fiscal_year`. It pulls each input's
number and citation from the data layer (facts.get_fact), runs the formula, and
returns the value with every input's provenance attached. Claude never supplies a
number; it only picks the company and year. pipeline/ binds these to the LLM with
forced tool_choice (LangChain bind_tools) — this layer stays provider-agnostic,
so no langchain import here (CLAUDE.md).
"""

import logging
from functools import lru_cache, partial
from pathlib import Path

import yaml

from tools import facts

log = logging.getLogger(__name__)

ONTOLOGY_PATH = Path(__file__).resolve().parent / "metrics.yaml"


@lru_cache(maxsize=1)
def ontology() -> dict:
    """Load metrics.yaml once. The single source of truth for every metric."""
    with open(ONTOLOGY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _cite(name: str, fiscal_year: int, tag_candidates: list[str], ticker: str) -> dict:
    """Pull one input and shape it as {name, value, citation}."""
    fact = facts.get_fact(ticker, tag_candidates, fiscal_year)
    return {"name": name, "value": fact["value"], "citation": fact}


def _result(metric: str, value: float, inputs: list[dict]) -> dict:
    m = ontology()[metric]
    return {
        "metric": metric,
        "value": value,
        "unit": m["unit"],
        "formula": m["formula"],
        "inputs": inputs,
    }


def _ratio(metric: str, ticker: str, fiscal_year: int) -> dict:
    """Generic num/den ratio, driven by the ontology. inputs[0] / inputs[1]."""
    m = ontology()[metric]
    num_name, den_name = m["inputs"]
    concepts = m["source_concept"]
    try:
        num = _cite(num_name, fiscal_year, concepts[num_name], ticker)
        den = _cite(den_name, fiscal_year, concepts[den_name], ticker)
    except LookupError as e:
        log.info("%s not available for %s FY%d: %s", metric, ticker, fiscal_year, e)
        return {"metric": metric, "is_error": True, "error": str(e)}
    if den["value"] == 0:
        log.warning("%s: %s is zero for %s FY%d — cannot divide", metric, den_name, ticker, fiscal_year)
        return {"metric": metric, "is_error": True, "error": f"{den_name} is zero"}
    value = round(num["value"] / den["value"], 6)
    log.debug("%s(%s, %d) = %s", metric, ticker, fiscal_year, value)
    return _result(metric, value, [num, den])


def revenue_growth(ticker: str, fiscal_year: int) -> dict:
    """(Revenue_t - Revenue_t-1) / Revenue_t-1. Needs two fiscal years."""
    m = ontology()["revenue_growth"]
    tags = m["source_concept"]["Revenue"]
    try:
        cur = _cite("Revenue_t", fiscal_year, tags, ticker)
        prev = _cite("Revenue_t_minus_1", fiscal_year - 1, tags, ticker)
    except LookupError as e:
        log.info("revenue_growth not available for %s FY%d: %s", ticker, fiscal_year, e)
        return {"metric": "revenue_growth", "is_error": True, "error": str(e)}
    if prev["value"] == 0:
        log.warning("revenue_growth: prior-year revenue is zero for %s FY%d", ticker, fiscal_year)
        return {"metric": "revenue_growth", "is_error": True, "error": "prior-year revenue is zero"}
    value = round((cur["value"] - prev["value"]) / prev["value"], 6)
    log.debug("revenue_growth(%s, %d) = %s", ticker, fiscal_year, value)
    return _result("revenue_growth", value, [cur, prev])


# name -> callable(ticker, fiscal_year). The three ratios share _ratio; the
# formula direction is the ontology `inputs` order.
REGISTRY = {
    "current_ratio": partial(_ratio, "current_ratio"),
    "roe": partial(_ratio, "roe"),
    "roa": partial(_ratio, "roa"),
    "debt_to_equity": partial(_ratio, "debt_to_equity"),
    "revenue_growth": revenue_growth,
}


def tool_specs() -> list[dict]:
    """Provider-agnostic {name, description, input_schema} per metric, built from
    the ontology so the schema never drifts from the formulas. pipeline/ feeds
    these to LangChain bind_tools with forced tool_choice."""
    specs = []
    for name, m in ontology().items():
        specs.append({
            "name": name,
            "description": (
                f"{m['definition']} Formula: {m['formula']}. "
                f"Computes the metric from a company's 10-K XBRL facts and returns "
                f"the value with a source citation for every input. "
                f"Result unit: {m['unit']}."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Company ticker, e.g. JPM."},
                    "fiscal_year": {"type": "integer", "description": "Fiscal year, e.g. 2025."},
                },
                "required": ["ticker", "fiscal_year"],
                "additionalProperties": False,
            },
        })
    return specs
