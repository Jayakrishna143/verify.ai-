"""Step 1 — download SEC EDGAR filings.

Resolve the 15 tickers to CIKs, pick the latest 10-K + two 10-Qs each, download
the primary HTML document and the XBRL companyfacts JSON, and write one manifest
row per document. All SEC I/O is stdlib urllib, throttled under 10 req/s.
"""

import json
import logging
import time
import urllib.error
import urllib.request

from ingest import config as cfg

log = logging.getLogger(__name__)

# --- Shared throttled fetchers (the one rate-limit point) --------------------


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": cfg.USER_AGENT})


def _fetch(url: str, retries: int = 2) -> bytes:
    """GET url with the UA header. Sleep after each call to stay under the
    rate cap. Retry a couple of times on 429 / transient network errors."""
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(_request(url)) as resp:
                data = resp.read()
            time.sleep(cfg.RATE_LIMIT_SLEEP)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                log.warning("429 Too Many Requests on %s — retry %d/%d", url, attempt + 1, retries)
                time.sleep(1.0 + attempt)
                continue
            log.error("HTTP %s fetching %s", e.code, url)
            raise
        except urllib.error.URLError as e:
            if attempt < retries:
                log.warning("network error on %s (%s) — retry %d/%d", url, e.reason, attempt + 1, retries)
                time.sleep(1.0 + attempt)
                continue
            log.error("giving up on %s after %d attempts: %s", url, retries + 1, e.reason)
            raise
    raise RuntimeError(f"unreachable: {url}")  # pragma: no cover


def http_get_bytes(url: str) -> bytes:
    return _fetch(url)


def http_get_json(url: str) -> dict:
    return json.loads(_fetch(url).decode("utf-8"))


# --- CIK resolution ----------------------------------------------------------


def resolve_ciks(tickers: list[str]) -> dict[str, str]:
    """Map each ticker to its zero-padded 10-digit CIK using company_tickers.json.
    Runtime resolution IS the Decision 6 CIK confirmation. Raises if a ticker is
    not found."""
    table = http_get_json(cfg.TICKERS_URL)
    by_ticker = {row["ticker"]: str(row["cik_str"]).zfill(10) for row in table.values()}
    missing = [t for t in tickers if t not in by_ticker]
    if missing:
        log.error("tickers not found in company_tickers.json: %s", missing)
        raise ValueError(f"tickers not found in company_tickers.json: {missing}")
    log.debug("resolved %d tickers to CIKs", len(tickers))
    return {t: by_ticker[t] for t in tickers}


# --- Filing selection --------------------------------------------------------


def pick_filings(recent: dict, n_10q: int = cfg.N_10Q) -> list[dict]:
    """Pick the latest 10-K and the latest n_10q 10-Qs from the columnar
    `filings.recent` block (parallel arrays, already newest-first)."""
    forms = recent["form"]
    picked: list[dict] = []
    seen_10k = False
    n_q = 0
    for i, form in enumerate(forms):
        if form == "10-K" and not seen_10k:
            seen_10k = True
        elif form == "10-Q" and n_q < n_10q:
            n_q += 1
        else:
            continue
        picked.append(
            {
                "form": form,
                "accession": recent["accessionNumber"][i],
                "primary_doc": recent["primaryDocument"][i],
                "filing_date": recent["filingDate"][i],
                "report_date": recent["reportDate"][i],
                "desc": recent.get("primaryDocDescription", [""] * len(forms))[i],
            }
        )
        if seen_10k and n_q >= n_10q:
            break
    return picked


def build_doc_url(cik10: str, accession: str, primary_doc: str) -> str:
    """Build the primary-document URL. The path uses the company CIK as int
    (leading zeros stripped), NOT the accession-number prefix — a company that
    files through an agent has a different accession prefix and would 404."""
    acc_nodash = accession.replace("-", "")
    return cfg.DOC_URL.format(cik_int=int(cik10), acc_nodash=acc_nodash, primary=primary_doc)


def fiscal_period(form: str, report_date: str) -> str:
    """FY{year} for a 10-K, Q{n}FY{year} for a 10-Q, from the reportDate month."""
    year, month, _ = report_date.split("-")
    if form == "10-K":
        return f"FY{year}"
    quarter = (int(month) - 1) // 3 + 1
    return f"Q{quarter}FY{year}"


def filename(ticker: str, form: str, report_date: str) -> str:
    """JPM_10-K_2025.html (year), JPM_10-Q_2026-06-30.html (full date so two
    quarters in one year do not collide)."""
    stamp = report_date[:4] if form == "10-K" else report_date
    return f"{ticker}_{form}_{stamp}.html"


# --- Per-company download ----------------------------------------------------


def download_company(ticker: str, cik10: str) -> list[dict]:
    """Download the picked filings + companyfacts for one company. Returns the
    manifest rows written. A single bad filing logs and is skipped."""
    cfg.CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    subs = http_get_json(cfg.SUBMISSIONS_URL.format(cik10=cik10))
    company = subs.get("name", ticker)

    # companyfacts once per company (the exact-number source for the tools layer).
    facts_path = cfg.CORPUS_DIR / f"{ticker}_facts.json"
    try:
        facts = http_get_bytes(cfg.FACTS_URL.format(cik10=cik10))
        facts_path.write_bytes(facts)
        facts_rel = str(facts_path)
    except urllib.error.HTTPError as e:
        log.warning("%s companyfacts: HTTP %s — skipping facts", ticker, e.code)
        facts_rel = ""

    rows: list[dict] = []
    for f in pick_filings(subs["filings"]["recent"]):
        url = build_doc_url(cik10, f["accession"], f["primary_doc"])
        out = cfg.CORPUS_DIR / filename(ticker, f["form"], f["report_date"])
        try:
            out.write_bytes(http_get_bytes(url))
        except urllib.error.HTTPError as e:
            log.warning("%s %s %s: HTTP %s — skipping", ticker, f["form"], f["report_date"], e.code)
            continue
        rows.append(
            {
                "ticker": ticker,
                "company": company,
                "cik": cik10,
                "form": f["form"],
                "fiscal_period": fiscal_period(f["form"], f["report_date"]),
                "accession": f["accession"],
                "filing_date": f["filing_date"],
                "report_date": f["report_date"],
                "primary_doc": f["primary_doc"],
                "filing_url": url,
                "local_path": str(out),
                "facts_path": facts_rel,
            }
        )
        log.info("+ %s", out.name)
    return rows


def main() -> None:
    ciks = resolve_ciks(cfg.TICKERS)
    cfg.CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    n_docs = 0
    with open(cfg.MANIFEST, "w", encoding="utf-8") as mf:
        for ticker in cfg.TICKERS:
            log.info("%s (CIK %s)", ticker, ciks[ticker])
            for row in download_company(ticker, ciks[ticker]):
                mf.write(json.dumps(row) + "\n")
                n_docs += 1
    log.info("download: %d documents, %d companies -> %s", n_docs, len(cfg.TICKERS), cfg.MANIFEST.name)


if __name__ == "__main__":
    main()
