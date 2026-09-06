"""Step 5 data layer — the deterministic bridge from an XBRL tag to a number
AND its citation.

This is the only code that reads a raw number. It reads the EDGAR companyfacts
JSON (downloaded by ingest step 1, in data/corpus/) and returns the fact for a
given tag + fiscal year, with the accession, form, and period that let a person
check it by hand. Claude never touches these numbers — it only names the ticker
and year (see metrics.py). That is the whole "verifiable" idea (Decision 11).
"""

import json
import logging
from functools import lru_cache

from ingest import config as ingest_cfg

log = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def load_facts(ticker: str) -> dict:
    """Load one company's us-gaap facts: {tag: {units: {USD: [fact, ...]}}}."""
    path = ingest_cfg.CORPUS_DIR / f"{ticker}_facts.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)["facts"]["us-gaap"]
    except FileNotFoundError:
        log.error("companyfacts missing for %s: %s (run `python -m ingest.run` step 1)", ticker, path)
        raise


def _strip(tag: str) -> str:
    """`us-gaap:Assets` -> `Assets`. companyfacts keys concepts without prefix."""
    return tag.split(":", 1)[-1]


def get_fact(ticker: str, tag_candidates: list[str], fiscal_year: int, form: str = "10-K") -> dict:
    """Return the primary annual fact for the first present tag.

    companyfacts holds the company's full filing history, so a year the local
    HTML corpus never downloaded still resolves here. Within one fiscal year a
    filing lists both the current-year figure and a prior-year comparative under
    the same `fy`; the current one has the later period end, so pick max `end`.

    Returns value + full citation. Raises if no candidate tag has a matching
    annual period — the caller (metrics.py) turns that into an is_error result.
    """
    gaap = load_facts(ticker)
    for tag in tag_candidates:
        concept = gaap.get(_strip(tag))
        if not concept:
            continue
        usd = concept.get("units", {}).get("USD", [])
        annual = [x for x in usd if x.get("form") == form and x.get("fy") == fiscal_year and x.get("fp") == "FY"]
        if not annual:
            continue
        fact = max(annual, key=lambda x: x["end"])  # current-year, not the comparative
        log.debug("%s %s FY%d: %s = %s (accn %s, end %s)", ticker, form, fiscal_year, tag, fact["val"], fact["accn"], fact["end"])
        return {
            "value": fact["val"],
            "line_item": tag,                       # the XBRL tag actually used
            "doc_id": f"{ticker}-{form}-FY{fiscal_year}",
            "accn": fact["accn"],                   # accession: the exact filing
            "form": form,
            "fy": fiscal_year,
            "end": fact["end"],                     # period end
            "filed": fact.get("filed"),
            "page": None,                           # null for HTML filings (Decision 7)
        }
    log.debug("%s: no %s in %s FY%d facts", ticker, tag_candidates, form, fiscal_year)
    raise LookupError(
        f"{ticker} does not report {' or '.join(tag_candidates)} in its "
        f"{form} XBRL facts (FY{fiscal_year}) — metric not available for this company"
    )
