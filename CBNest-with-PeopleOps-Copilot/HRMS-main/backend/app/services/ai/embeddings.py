"""
Embedding generation for the Policy RAG pipeline.

Design decision (see docs/ai_architecture.md): instead of an external
embedding API or a downloaded sentence-transformer model, we fit a TF-IDF
vector space over the HR policy corpus itself — fully offline,
numpy-only, deterministic, and effective for this closed-domain,
few-dozen-document retrieval task. Swapping to a hosted embeddings API
later only means re-implementing `embed_text`/`fit_vocabulary` here.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

import numpy as np

VOCAB_PATH = Path(__file__).resolve().parents[3] / "storage" / "ai" / "vocab.json"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def fit_vocabulary(documents: Iterable[str]) -> dict:
    docs_tokens = [tokenize(d) for d in documents]
    df: Counter = Counter()
    for tokens in docs_tokens:
        for term in set(tokens):
            df[term] += 1

    n_docs = max(len(docs_tokens), 1)
    vocab = {term: idx for idx, term in enumerate(sorted(df.keys()))}
    idf = {term: math.log((n_docs + 1) / (freq + 1)) + 1.0 for term, freq in df.items()}
    return {"vocab": vocab, "idf": idf, "n_docs": n_docs}


def save_vocabulary(vocab_data: dict) -> None:
    VOCAB_PATH.parent.mkdir(parents=True, exist_ok=True)
    VOCAB_PATH.write_text(json.dumps(vocab_data))


def load_vocabulary() -> dict:
    if not VOCAB_PATH.exists():
        raise RuntimeError(
            "Policy vocabulary not found. Run `python -m scripts.ingest_policies` "
            "(from backend/) to index the HR policy library first."
        )
    return json.loads(VOCAB_PATH.read_text())


def embed_text(text: str, vocab_data: dict) -> list[float]:
    vocab = vocab_data["vocab"]
    idf = vocab_data["idf"]
    tokens = tokenize(text)
    counts = Counter(tokens)
    vec = np.zeros(len(vocab), dtype=np.float32)
    total = max(len(tokens), 1)
    for term, count in counts.items():
        idx = vocab.get(term)
        if idx is None:
            continue
        tf = count / total
        vec[idx] = tf * idf.get(term, 1.0)

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    denom = (np.linalg.norm(va) * np.linalg.norm(vb)) or 1e-9
    return float(np.dot(va, vb) / denom)
