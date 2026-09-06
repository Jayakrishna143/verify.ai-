"""Orchestrator + self-checks for the ingest step.

    uv run python -m ingest.run          # self-checks, then download + chunk
    uv run python -m ingest.run --chunk  # skip download, re-chunk the corpus

The self-checks are assert-based and cover the load-bearing logic (CIK padding,
the document-URL rule, filing selection). They run before any network call.
"""

import logging
import sys

from ingest import config as cfg
from ingest import download, chunk
from logconf import setup_logging

log = logging.getLogger(__name__)


def self_check() -> None:
    # CIK zero-padding.
    assert str(320193).zfill(10) == "0000320193"

    # Document URL uses the company CIK as int, NOT the accession prefix. JPM
    # files through an agent (accession prefix 1628280) yet the path is /19617/.
    url = download.build_doc_url("0000019617", "0001628280-26-008131", "jpm-20251231.htm")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/19617/000162828026008131/jpm-20251231.htm"
    ), url

    # Filing selection: 1 x 10-K + 2 x 10-Q, newest-first, from columnar arrays.
    recent = {
        "form": ["10-Q", "8-K", "10-Q", "10-Q", "10-K", "10-K"],
        "accessionNumber": ["a", "b", "c", "d", "e", "f"],
        "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm", "e.htm", "f.htm"],
        "filingDate": ["6", "5", "4", "3", "2", "1"],
        "reportDate": [
            "2026-06-30", "2026-05-01", "2026-03-31",
            "2025-12-31", "2025-12-31", "2024-12-31",
        ],
    }
    picked = download.pick_filings(recent, n_10q=2)
    assert [p["form"] for p in picked] == ["10-Q", "10-Q", "10-K"], picked
    assert [p["accession"] for p in picked] == ["a", "c", "e"], picked

    # Fiscal-period formatting.
    assert download.fiscal_period("10-K", "2025-12-31") == "FY2025"
    assert download.fiscal_period("10-Q", "2026-06-30") == "Q2FY2026"

    # Heading detection.
    assert chunk.is_heading("Item 7. Management's Discussion")
    assert chunk.is_heading("CONSOLIDATED BALANCE SHEETS")
    assert not chunk.is_heading("The company reported net income of $5.0 billion.")

    log.info("self-check: ok")


def main() -> None:
    setup_logging()
    self_check()
    if "--chunk" in sys.argv:
        chunk.main()
        return
    download.main()
    chunk.main()


if __name__ == "__main__":
    main()
