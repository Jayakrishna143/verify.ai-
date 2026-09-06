"""Constants for the ingest step. No logic here — just values the other
ingest modules read."""

from pathlib import Path

# --- Corpus (Decision 6) -----------------------------------------------------
# 15 finance-sector tickers. CIKs are resolved live at runtime from
# company_tickers.json (see download.resolve_ciks). EXPECTED_CIK is only a
# self-check guard.
TICKERS = [
    "JPM", "BAC", "GS", "MS", "USB", "PNC", "COF", "AXP",
    "V", "MA", "BLK", "SCHW", "MET", "TRV", "CB",
]

# Live-verified 2026-08-13. Note BLK = 0002012383, which corrects the
# 0001364742 guess in Decision 6. Used only by the run.py assert self-check.
EXPECTED_CIK = {
    "JPM": "0000019617", "BAC": "0000070858", "GS": "0000886982",
    "MS": "0000895421", "USB": "0000036104", "PNC": "0000713676",
    "COF": "0000927628", "AXP": "0000004962", "V": "0001403161",
    "MA": "0001141391", "BLK": "0002012383", "SCHW": "0000316709",
    "MET": "0001099219", "TRV": "0000086312", "CB": "0000896159",
}

# Per company: latest 10-K + latest N_10Q 10-Qs -> ~45 docs, under the 50 cap.
N_10Q = 2

# --- SEC access (step 1 rules) ----------------------------------------------
# The SEC rejects requests with no proper User-Agent (HTTP 403). Name + email.
USER_AGENT = "ReKnew Research herigela@reknew.ai"

# Fair-access cap is 10 requests/second. 0.15s between calls -> ~6-7 req/s.
RATE_LIMIT_SLEEP = 0.15

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
# {cik_int} is the COMPANY cik as int (e.g. 19617), NOT the accession prefix.
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary}"

# --- Chunking (step 2) -------------------------------------------------------
CHUNK_TOKENS = 512
CHUNK_OVERLAP = 64  # HybridChunker approximates this via peer-merge, not a literal window.

# --- Paths -------------------------------------------------------------------
INGEST_DIR = Path(__file__).resolve().parent
ROOT = INGEST_DIR.parent
CORPUS_DIR = ROOT / "data" / "corpus"
MANIFEST = INGEST_DIR / "manifest.jsonl"
CHUNKS = INGEST_DIR / "chunks.jsonl"
