"""Retrieval for RAG: find the knowledge-base entries most relevant to a question.

Two interchangeable embedders:
  - TF-IDF (default): offline, no model download, fast for a small knowledge base.
  - Provider embeddings: any OpenAI-compatible /embeddings endpoint (OpenAI,
    Ollama's nomic-embed-text, ...), which also matches synonyms and paraphrases.

Either way the result is the same: vectors compared with cosine similarity,
top-k hits returned with their scores so the UI can show what was used.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass

from django.conf import settings

from ..models import KnowledgeDoc
from .llm import post_json

STOPWORDS = set(
    "a an and are as at be by did do does for from has have how i in is it its of on or our show "
    "tell that the their them there this to us was we were what when where which who why with you "
    "me my give list each per vs versus".split()
)
MIN_SCORE = 0.04


@dataclass
class Hit:
    doc_id: int
    title: str
    kind: str
    content: str
    score: float

    def as_dict(self, with_content: bool = False) -> dict:
        data = {"id": self.doc_id, "title": self.title, "kind": self.kind, "score": round(self.score, 3)}
        if with_content:
            data["content"] = self.content
        return data


def tokenize(text: str) -> list[str]:
    tokens = []
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word in STOPWORDS or len(word) < 2:
            continue
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            word = word[:-1]
        tokens.append(word)
    return tokens


def _cosine_sparse(a: dict, b: dict) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _cosine_dense(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class TfidfEmbedder:
    """Sparse TF-IDF vectors (sublinear tf, smoothed idf), fit on the current documents."""

    def fit(self, texts: list[str]) -> list[dict]:
        docs = [Counter(tokenize(t)) for t in texts]
        n = len(docs)
        df = Counter(term for doc in docs for term in doc)
        self.idf = {term: math.log((1 + n) / (1 + count)) + 1 for term, count in df.items()}
        return [self._weigh(doc) for doc in docs]

    def _weigh(self, counts: Counter) -> dict:
        return {t: (1 + math.log(c)) * self.idf[t] for t, c in counts.items() if t in self.idf}

    def embed_query(self, text: str) -> dict:
        return self._weigh(Counter(tokenize(text)))


def _embed_remote(texts: list[str]) -> list[list[float]]:
    headers = {"Authorization": f"Bearer {settings.EMBEDDINGS_API_KEY}"} if settings.EMBEDDINGS_API_KEY else {}
    base = (settings.EMBEDDINGS_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    data = post_json(
        f"{base}/embeddings",
        {"model": settings.EMBEDDINGS_MODEL, "input": texts},
        headers=headers,
        timeout=60,
        label="embeddings",
    )
    return [item["embedding"] for item in sorted(data["data"], key=lambda d: d["index"])]


def _embedding_key(doc: KnowledgeDoc) -> str:
    digest = hashlib.sha1(doc.search_text.encode()).hexdigest()[:16]
    return f"{settings.EMBEDDINGS_MODEL}:{digest}"


def search(query: str, k: int | None = None) -> list[Hit]:
    k = k or settings.RAG_TOP_K
    docs = list(KnowledgeDoc.objects.all())
    if not docs or not query.strip():
        return []

    if settings.EMBEDDINGS_BACKEND == "openai":
        stale = [d for d in docs if d.embedding_key != _embedding_key(d) or not d.embedding]
        if stale:
            for doc, vector in zip(stale, _embed_remote([d.search_text for d in stale])):
                doc.embedding, doc.embedding_key = vector, _embedding_key(doc)
                doc.save(update_fields=["embedding", "embedding_key"])
        query_vec = _embed_remote([query])[0]
        scores = [_cosine_dense(query_vec, d.embedding) for d in docs]
        min_score = 0.2
    else:
        embedder = TfidfEmbedder()
        vectors = embedder.fit([d.search_text for d in docs])
        query_vec = embedder.embed_query(query)
        scores = [_cosine_sparse(query_vec, v) for v in vectors]
        min_score = MIN_SCORE

    ranked = sorted(zip(docs, scores), key=lambda pair: pair[1], reverse=True)
    return [
        Hit(doc.id, doc.title, doc.kind, doc.content, score)
        for doc, score in ranked[:k]
        if score >= min_score
    ]
