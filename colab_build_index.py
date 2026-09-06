# =====================================================================
# Colab: build the retrieval hybrid index on GPU, then download it.
#
# Why: the local WSL VM (2 cores, 1.9 GB RAM) is too slow/small to embed
# 9,992 chunks. Colab embeds them on GPU in minutes. You download the
# finished Qdrant index and drop it into retrieval/qdrant_data/ locally.
# Local search only embeds ONE query string at a time, so the small VM
# handles queries fine — it never re-embeds the corpus.
#
# GPU note: the dense model runs through sentence-transformers (PyTorch),
# because Colab's torch+CUDA works out of the box. fastembed-gpu (ONNX)
# often silently falls back to CPU on Colab due to a CUDA mismatch. BM25
# is a light Rust/CPU model, so it stays on fastembed. The vectors are the
# same bge-base-en-v1.5 weights, unit-normalized, so the index reads back
# correctly with the local fastembed query path.
#
# HOW TO USE
#   1. Runtime -> Change runtime type -> GPU (T4 is fine). Paste this whole
#      file into one Colab cell and run it.
#   2. When prompted, upload ingest/chunks.jsonl from your machine.
#   3. It embeds everything, then downloads qdrant_data.zip.
#   4. On your machine, unzip it into retrieval/ so you get
#      retrieval/qdrant_data/ (commands printed at the end).
#
# IMPORTANT: DENSE_MODEL / DENSE_DIM / COLLECTION / the vector names
# ("dense", "sparse") and the IDF modifier below MUST match
# retrieval/config.py and retrieval/index.py, or local search will not
# read this index.
# =====================================================================

# qdrant-client is pinned to the local version so the on-disk storage
# format matches exactly. sentence-transformers gives GPU dense embedding;
# fastembed gives the BM25 sparse vectors.
# pip -q install "qdrant-client==1.19.0" sentence-transformers fastembed >/dev/null

import json
import torch
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from fastembed import SparseTextEmbedding

# --- must match retrieval/config.py ---
DENSE_MODEL = "BAAI/bge-base-en-v1.5"
DENSE_DIM = 768
SPARSE_MODEL = "Qdrant/bm25"
COLLECTION = "filings"
QDRANT_PATH = "qdrant_data"
UPSERT_BATCH = 512
EMBED_BATCH = 256

# --- 1. upload chunks.jsonl ---
from google.colab import files
print("Upload ingest/chunks.jsonl:")
files.upload()  # -> ./chunks.jsonl
CHUNKS = "chunks.jsonl"

rows = [json.loads(line) for line in open(CHUNKS, encoding="utf-8")]
texts = [r["text"] for r in rows]
print(f"{len(rows)} chunks loaded")

# --- 2. dense embeddings on GPU (sentence-transformers / PyTorch) ---
device = "cuda" if torch.cuda.is_available() else "cpu"
print("device:", device)  # must say 'cuda'
assert device == "cuda", "No GPU. Runtime -> Change runtime type -> GPU, then re-run."
st = SentenceTransformer(DENSE_MODEL, device=device)
# normalize_embeddings=True -> unit vectors, matching fastembed's bge output
# and the cosine distance set on the collection. No query prefix on passages.
dense_vecs = st.encode(
    texts, batch_size=EMBED_BATCH, normalize_embeddings=True,
    convert_to_numpy=True, show_progress_bar=True,
)
assert dense_vecs.shape[1] == DENSE_DIM, dense_vecs.shape

# --- 3. sparse BM25 (fastembed, CPU — light and fast) ---
sparse = SparseTextEmbedding(SPARSE_MODEL)
sparse_vecs = list(sparse.embed(texts, batch_size=EMBED_BATCH))

# --- 4. fresh collection: named dense + sparse vectors, IDF on sparse ---
client = QdrantClient(path=QDRANT_PATH)
if client.collection_exists(COLLECTION):
    client.delete_collection(COLLECTION)
client.create_collection(
    collection_name=COLLECTION,
    vectors_config={"dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE)},
    sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
)

# --- 5. upsert points (raw precomputed vectors + full chunk payload) ---
from tqdm.auto import tqdm
batch = []
for i in tqdm(range(len(rows)), unit="chunk"):
    sv = sparse_vecs[i]
    batch.append(
        models.PointStruct(
            id=i,
            vector={
                "dense": dense_vecs[i].tolist(),
                "sparse": models.SparseVector(indices=sv.indices.tolist(), values=sv.values.tolist()),
            },
            payload=rows[i],
        )
    )
    if len(batch) >= UPSERT_BATCH:
        client.upsert(COLLECTION, points=batch)
        batch = []
if batch:
    client.upsert(COLLECTION, points=batch)

print("indexed count:", client.count(COLLECTION).count)
del client  # release the on-disk lock before zipping

# --- 6. zip and download ---
import shutil
shutil.make_archive("qdrant_data", "zip", "qdrant_data")
files.download("qdrant_data.zip")

print(r"""
DONE. On your machine (WSL, repo root):
  mkdir -p retrieval/qdrant_data
  unzip -o ~/Downloads/qdrant_data.zip -d retrieval/qdrant_data
  # check: retrieval/qdrant_data/collection/ and retrieval/qdrant_data/meta.json exist
  uv run python -m retrieval.run "current ratio of JPMorgan"
""")
