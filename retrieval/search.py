"""Step 3 runtime — hybrid dense+sparse retrieval, RRF-fused.

`search()` is the function pipeline/ imports. One Qdrant Query API call does the
dense search, the sparse search, and the RRF merge. Each result is the full
chunk payload plus a `score`, so citation anchors (doc_id, section_id,
line_item) come back untouched.
"""

import logging
from functools import lru_cache

from qdrant_client import QdrantClient, models

from retrieval import config as cfg

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _client() -> QdrantClient:
    """Open the embedded client once and reuse it across queries."""
    if not cfg.QDRANT_PATH.exists():
        log.warning("Qdrant data dir %s is missing — build or unzip the index first (see Handover.md)", cfg.QDRANT_PATH)
    log.debug("opening embedded Qdrant at %s", cfg.QDRANT_PATH)
    return QdrantClient(path=str(cfg.QDRANT_PATH))


def _shape(points: list) -> list[dict]:
    """Flatten Qdrant scored points into chunk-payload dicts + score."""
    return [{**p.payload, "score": p.score} for p in points]


def search(query: str, limit: int = cfg.FINAL_LIMIT) -> list[dict]:
    """Return the top `limit` chunks for `query`, highest RRF score first.

    fastembed applies the BGE query prefix automatically on the dense query
    path, so pass the raw question. Qdrant's RRF uses k=60 by default.
    """
    log.debug("hybrid search %r (prefetch=%d, limit=%d)", query, cfg.PREFETCH_LIMIT, limit)
    result = _client().query_points(
        collection_name=cfg.COLLECTION,
        prefetch=[
            models.Prefetch(
                query=models.Document(text=query, model=cfg.DENSE_MODEL),
                using="dense",
                limit=cfg.PREFETCH_LIMIT,
            ),
            models.Prefetch(
                query=models.Document(text=query, model=cfg.SPARSE_MODEL),
                using="sparse",
                limit=cfg.PREFETCH_LIMIT,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    hits = _shape(result.points)
    log.info("search %r -> %d hits", query, len(hits))
    if not hits:
        log.warning("no hits for %r — empty collection or over-narrow query", query)
    return hits
