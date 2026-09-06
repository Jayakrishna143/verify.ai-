"""Step 2 — chunk filings into chunks.jsonl with source metadata.

Reads the HTML filings listed in manifest.jsonl, strips them to text, detects
the SEC section heading (Item N / statement title) that each chunk sits under,
and packs the text into ~512-token chunks with ~64-token overlap. Each chunk
carries the full step-2 metadata schema.

Why bs4, not Docling: Docling on real SEC iXBRL was slow (~2 min/file),
extracted no section headings, and mangled the financial tables into gibberish.
The deterministic numbers come from the XBRL companyfacts JSON, not from chunk
text, so a chunk's job is to locate human-readable context. bs4 does that fast
and lets us control section detection.
# ponytail: token_count is a word-based estimate, not a real tokenizer count.
# Swap in a tokenizer only if chunk sizing proves off during retrieval tuning.
"""

import json
import logging
import re

from bs4 import BeautifulSoup

from ingest import config as cfg

log = logging.getLogger(__name__)

# A 10-K Item ("Item 7."), a 10-Q Item, or PART I/II.
_ITEM_RE = re.compile(r"^(item\s+\d+[a-z]?|part\s+[ivx]+)\b[\.\:\)\s]", re.IGNORECASE)


def est_tokens(text: str) -> int:
    """Rough token estimate: words * 1.3. Good enough for chunk sizing."""
    return max(1, round(len(text.split()) * 1.3))


def is_heading(line: str) -> bool:
    """A section heading is either an `Item N` / `PART` line, or a short
    ALL-CAPS statement title such as CONSOLIDATED BALANCE SHEETS."""
    if _ITEM_RE.match(line):
        return True
    letters = [c for c in line if c.isalpha()]
    if 8 <= len(line) <= 90 and len(letters) >= 6 and line == line.upper():
        return True
    return False


def extract_blocks(html: str) -> list[tuple[bool, str]]:
    """Return ordered (is_heading, text) blocks from a filing. One block per
    non-empty text line of the stripped document."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    blocks: list[tuple[bool, str]] = []
    for raw in soup.get_text("\n").split("\n"):
        line = " ".join(raw.split())  # collapse whitespace
        if line:
            blocks.append((is_heading(line), line))
    return blocks


def chunk_blocks(blocks: list[tuple[bool, str]]) -> list[dict]:
    """Pack blocks into ~512-token chunks with ~64-token overlap. Each chunk
    records the section heading active at its start and char offsets into the
    reconstructed clean text."""
    # Reconstruct the clean text and remember each block's char offset + section.
    clean_parts: list[str] = []
    offsets: list[int] = []
    sections: list[str | None] = []
    cursor = 0
    current_section: str | None = None
    for is_head, text in blocks:
        if is_head:
            current_section = text[:90]
        offsets.append(cursor)
        sections.append(current_section)
        clean_parts.append(text)
        cursor += len(text) + 1  # +1 for the "\n" join
    clean = "\n".join(clean_parts)

    chunks: list[dict] = []
    i = 0
    n = len(blocks)
    while i < n:
        start_block = i
        char_start = offsets[i]
        section_id = sections[i]
        tok = 0
        j = i
        while j < n and tok < cfg.CHUNK_TOKENS:
            tok += est_tokens(blocks[j][1])
            j += 1
        end_block = j  # exclusive
        char_end = offsets[end_block - 1] + len(blocks[end_block - 1][1])
        text = clean[char_start:char_end]
        chunks.append(
            {
                "section_id": section_id,
                "char_start": char_start,
                "char_end": char_end,
                "token_count": est_tokens(text),
                "text": text,
            }
        )
        if end_block >= n:
            break
        # Overlap: step back ~CHUNK_OVERLAP tokens worth of blocks.
        back = 0
        k = end_block
        while k > start_block + 1 and back < cfg.CHUNK_OVERLAP:
            k -= 1
            back += est_tokens(blocks[k][1])
        i = k
    return chunks


def build_chunk_record(row: dict, idx: int, ch: dict) -> dict:
    doc_id = f"{row['ticker']}-{row['form']}-{row['fiscal_period']}"
    return {
        "chunk_id": f"{doc_id}#{idx:04d}",
        "doc_id": doc_id,
        "company": row["company"],
        "cik": row["cik"],
        "filing_type": row["form"],
        "fiscal_period": row["fiscal_period"],
        "source_path": row["local_path"],
        "page": None,  # ponytail: HTML/iXBRL has no pages; section_id + char offsets are the anchor.
        "section_id": ch["section_id"],
        "line_item": None,  # filled later from XBRL if a chunk maps to a tagged figure.
        "char_start": ch["char_start"],
        "char_end": ch["char_end"],
        "token_count": ch["token_count"],
        "text": ch["text"],
    }


def main() -> None:
    rows = [json.loads(l) for l in open(cfg.MANIFEST, encoding="utf-8")]
    n_chunks = 0
    with open(cfg.CHUNKS, "w", encoding="utf-8") as out:
        for row in rows:
            try:
                html = open(row["local_path"], encoding="utf-8", errors="replace").read()
                chunks = chunk_blocks(extract_blocks(html))
            except Exception:  # one bad file must not kill the batch
                log.error("failed to chunk %s — skipping", row["local_path"], exc_info=True)
                continue
            missing = sum(1 for ch in chunks if ch["section_id"] is None)
            for idx, ch in enumerate(chunks):
                out.write(json.dumps(build_chunk_record(row, idx, ch)) + "\n")
            n_chunks += len(chunks)
            log.info("+ %s %s %s: %d chunks", row["ticker"], row["form"], row["fiscal_period"], len(chunks))
            if missing:
                log.debug("%s %s: %d/%d chunks have no section_id", row["ticker"], row["form"], missing, len(chunks))
    log.info("chunk: %d chunks from %d documents -> %s", n_chunks, len(rows), cfg.CHUNKS.name)


if __name__ == "__main__":
    main()
