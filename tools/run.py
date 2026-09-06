"""Orchestrator + self-checks for the tools step (steps 4 + 5).

    uv run python -m tools.run              # assert self-checks only (offline)
    uv run python -m tools.run JPM 2025     # compute every metric + citations

The self-checks are assert-based and cover the load-bearing logic: the data
layer's period-selection rule (max end within a fiscal year), the citation shape
every number must carry, the GS revenue fallback tag, and the zero-denominator
guard. They read only local companyfacts JSON — no network, no model, no API.
"""

import logging
import sys

from tools import facts
from tools.metrics import REGISTRY, ontology, tool_specs
from logconf import setup_logging

log = logging.getLogger(__name__)


def self_check() -> None:
    # Ontology: 5 metrics, each fully specified.
    onto = ontology()
    assert set(onto) == {"current_ratio", "roe", "roa", "debt_to_equity", "revenue_growth"}, list(onto)
    for name, m in onto.items():
        assert m["formula"] and m["inputs"] and m["source_concept"], name

    # Data layer: fixed known value + the period-selection rule. JPM FY2025
    # equity is 362438000000 (the current-year figure, not the 2024 comparative
    # that shares fy=2025 in the same filing).
    eq = facts.get_fact("JPM", ["us-gaap:StockholdersEquity"], 2025)
    assert eq["value"] == 362438000000, eq
    assert eq["form"] == "10-K" and eq["end"] == "2025-12-31", eq
    assert eq["accn"] and eq["doc_id"] == "JPM-10-K-FY2025", eq

    # Every computed number carries a full citation (doc_id + line_item + accn).
    roe = REGISTRY["roe"]("JPM", 2025)
    assert "is_error" not in roe, roe
    assert round(57048000000 / 362438000000, 6) == roe["value"], roe
    for inp in roe["inputs"]:
        c = inp["citation"]
        assert c["doc_id"] and c["line_item"].startswith("us-gaap:") and c["accn"], c

    # GS revenue resolves via the fallback tag (GS has no us-gaap:Revenues).
    rg = REGISTRY["revenue_growth"]("GS", 2025)
    assert "is_error" not in rg, rg
    assert rg["inputs"][0]["citation"]["line_item"] == "us-gaap:RevenuesNetOfInterestExpense", rg

    # Tag-migration fallbacks are load-bearing (Decision 13). V dropped the plain
    # equity/revenue tags years ago; it must still resolve via the variants.
    v_roe = REGISTRY["roe"]("V", 2025)
    assert "is_error" not in v_roe, v_roe
    assert v_roe["inputs"][1]["citation"]["line_item"].endswith("IncludingPortionAttributableToNoncontrollingInterest"), v_roe
    v_rg = REGISTRY["revenue_growth"]("V", 2025)
    assert "is_error" not in v_rg, v_rg
    assert v_rg["inputs"][0]["citation"]["line_item"] == "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", v_rg

    # Net income migrates too: PNC and MA tag ProfitLoss, not NetIncomeLoss.
    pnc = REGISTRY["roe"]("PNC", 2025)
    assert "is_error" not in pnc, pnc
    assert pnc["inputs"][0]["citation"]["line_item"] == "us-gaap:ProfitLoss", pnc

    # Priority order picks the TOP LINE, not a sub-component. AXP has both
    # RevenuesNetOfInterestExpense (72.2B top line) and RevenueFromContract
    # (41.3B component) at FY2025 — it must choose the former.
    axp = REGISTRY["revenue_growth"]("AXP", 2025)
    assert axp["inputs"][0]["citation"]["line_item"] == "us-gaap:RevenuesNetOfInterestExpense", axp
    assert axp["inputs"][0]["value"] == 72229000000, axp

    # current_ratio: works for a filer with a classified balance sheet (V),
    # returns a clean "not available" for a bank that has no AssetsCurrent (JPM).
    assert "is_error" not in REGISTRY["current_ratio"]("V", 2025), "V current_ratio"
    jpm_cr = REGISTRY["current_ratio"]("JPM", 2025)
    assert jpm_cr.get("is_error") is True and "not available" in jpm_cr["error"], jpm_cr

    # Missing period -> is_error, not a crash.
    bad = REGISTRY["roe"]("JPM", 1990)
    assert bad.get("is_error") is True, bad

    # Tool specs stay in sync with the ontology (one per metric).
    assert {s["name"] for s in tool_specs()} == set(onto)

    log.info("self-check: ok")


def main() -> None:
    setup_logging()
    self_check()
    argv = sys.argv[1:]
    if len(argv) < 2:
        print('usage: <TICKER> <FISCAL_YEAR>   e.g. JPM 2025')
        return

    ticker, year = argv[0].upper(), int(argv[1])
    for name, func in REGISTRY.items():
        r = func(ticker, year)
        if r.get("is_error"):
            print(f"\n{name}: ERROR — {r['error']}")
            continue
        print(f"\n{name} = {r['value']}  ({r['unit']})   {r['formula']}")
        for inp in r["inputs"]:
            c = inp["citation"]
            print(f"    {inp['name']:20} {inp['value']:>18,}  [{c['line_item']} · {c['doc_id']} · accn {c['accn']} · {c['end']}]")


if __name__ == "__main__":
    main()
