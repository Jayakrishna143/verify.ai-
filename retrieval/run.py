"""Orchestrator + self-checks for the retrieval step.

    uv run python -m retrieval.run                 # self-checks only
    uv run python -m retrieval.run --build         # build the on-disk index
    uv run python -m retrieval.run --build --force # rebuild from scratch
    uv run python -m retrieval.run "current ratio of JPMorgan"  # query

The self-checks are assert-based and cover the pure, load-bearing logic (the
IDF-modifier collection config and the result-shaping contract). They need no
network and no model download. The real hybrid query runs on the CLI, where
fastembed downloads the models on first use.
"""

import logging
import sys
from types import SimpleNamespace

from qdrant_client import models

from retrieval import config as cfg
from retrieval import index, search
from logconf import setup_logging

log = logging.getLogger(__name__)


def self_check() -> None:
    # Collection config: the sparse side must carry the IDF modifier, or BM25
    # will not weight rare tokens. This is the easiest thing to get wrong.
    kw = index._collection_kwargs()
    assert kw["sparse_vectors_config"]["sparse"].modifier == models.Modifier.IDF, kw
    assert kw["vectors_config"]["dense"].size == cfg.DENSE_DIM, kw
    assert kw["vectors_config"]["dense"].distance == models.Distance.COSINE, kw

    # Result shaping: pipeline's citation contract. Every hit must expose the
    # full payload plus a score, so doc_id / section_id / line_item survive.
    fake = SimpleNamespace(
        payload={"doc_id": "JPM-10-K-FY2025", "section_id": "Item 7", "line_item": None, "text": "x"},
        score=0.5,
    )
    shaped = search._shape([fake])
    assert shaped == [
        {"doc_id": "JPM-10-K-FY2025", "section_id": "Item 7", "line_item": None, "text": "x", "score": 0.5}
    ], shaped

    log.info("self-check: ok")


def main() -> None:
    setup_logging()
    self_check()
    argv = sys.argv[1:]

    if "--build" in argv:
        index.build(force="--force" in argv)
        return

    queries = [a for a in argv if not a.startswith("--")]
    if not queries:
        print('usage: --build [--force] | "your question"')
        return

    for q in queries:
        print(f"\nquery: {q!r}")
        for i, hit in enumerate(search.search(q), 1):
            print(f"  {i:2d}. [{hit['score']:.4f}] {hit['doc_id']} / {hit['section_id']}")


if __name__ == "__main__":
    main()
