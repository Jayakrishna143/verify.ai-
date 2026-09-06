"""Step 3 build — load chunks.jsonl into an embedded Qdrant collection.

Run once, offline. Creates one collection with two named vectors per chunk:
a dense vector (bge-small-en-v1.5, meaning) and a sparse BM25 vector (exact
tokens). fastembed computes both locally on upsert — no manual encode call.

The whole chunk record is stored as the point payload, so doc_id / section_id /
line_item flow to citations for free.
"""

import json
import logging

from qdrant_client import QdrantClient, models
from tqdm import tqdm

from retrieval import config as cfg  # sets FASTEMBED_CACHE_PATH before any download

log = logging.getLogger(__name__)


def _collection_kwargs() -> dict:
    """Collection config: named dense + sparse vectors. The IDF modifier on the
    sparse side is load-bearing — it applies the inverse-document-frequency part
    of BM25 so rare tokens (a ticker, a line item) count more."""
    return {
        "collection_name": cfg.COLLECTION,
        "vectors_config": {
            "dense": models.VectorParams(
                size=cfg.DENSE_DIM, distance=models.Distance.COSINE
            ),
        },
        "sparse_vectors_config": {
            "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF),
        },
    }


def _point(idx: int, record: dict) -> models.PointStruct:
    text = record["text"]
    return models.PointStruct(
        id=idx,  # Qdrant needs int/UUID ids; chunk_id string lives in the payload.
        vector={
            # No query prefix on stored passages — correct for BGE (Decision 9).
            "dense": models.Document(text=text, model=cfg.DENSE_MODEL),
            "sparse": models.Document(text=text, model=cfg.SPARSE_MODEL),
        },
        payload=record,
    )


def _count_chunks() -> int:
    with open(cfg.CHUNKS, encoding="utf-8") as f:
        return sum(1 for _ in f)


def build(force: bool = False) -> None:
    client = QdrantClient(path=str(cfg.QDRANT_PATH))
    total = _count_chunks()

    if client.collection_exists(cfg.COLLECTION):
        have = client.count(cfg.COLLECTION).count
        if not force and have == total:
            log.info("collection '%s' already has %d points — skip", cfg.COLLECTION, have)
            return
        log.info("recreating '%s' (had %d, want %d)", cfg.COLLECTION, have, total)
        client.delete_collection(cfg.COLLECTION)

    client.create_collection(**_collection_kwargs())
    log.info("building index: %d chunks -> '%s' (model %s, first run downloads it)", total, cfg.COLLECTION, cfg.DENSE_MODEL)

    batch: list[models.PointStruct] = []
    done = 0
    try:
        with open(cfg.CHUNKS, encoding="utf-8") as f:
            for idx, line in enumerate(tqdm(f, total=total, unit="chunk", desc="index")):
                batch.append(_point(idx, json.loads(line)))
                if len(batch) >= cfg.UPSERT_BATCH:
                    client.upsert(cfg.COLLECTION, points=batch)
                    done += len(batch)
                    batch = []
        if batch:
            client.upsert(cfg.COLLECTION, points=batch)
            done += len(batch)
    except Exception:
        log.error("index build failed after %d/%d chunks (disk space or model download?)", done, total, exc_info=True)
        raise
    log.info("index: %d chunks -> collection '%s'", done, cfg.COLLECTION)
