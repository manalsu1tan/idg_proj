from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime, timezone


STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "be",
    "for",
    "from",
    "had",
    "has",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "our",
    "she",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "with",
    "you",
}


def tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9']+", text.lower()) if token and token not in STOPWORDS]


def unique_topics(text: str, limit: int = 5) -> list[str]:
    counts = Counter(tokenize(text))
    return [item for item, _ in counts.most_common(limit)]


def extract_entities(text: str) -> list[str]:
    matches = re.findall(r"\b[A-Z][a-zA-Z]+\b", text)
    seen: list[str] = []
    for item in matches:
        if item not in seen:
            seen.append(item)
    return seen[:5]


def token_count(text: str) -> int:
    return max(len(text.split()), 1)


def source_hash(items: list[str]) -> str:
    digest = hashlib.sha256()
    for item in items:
        digest.update(item.encode("utf-8"))
    return digest.hexdigest()


def jaccard_similarity(left: str, right: str) -> float:
    left_tokens = set(tokenize(left))
    right_tokens = set(tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def relevance_score(query: str, text: str) -> float:
    overlap = jaccard_similarity(query, text)
    query_counts = Counter(tokenize(query))
    text_counts = Counter(tokenize(text))
    weighted = 0.0
    for token, count in query_counts.items():
        weighted += min(count, text_counts[token])
    total = max(sum(query_counts.values()), 1)
    return min(1.0, overlap + (weighted / total) * 0.5)


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def recency_score(reference: datetime, event_time: datetime) -> float:
    reference = normalize_datetime(reference)
    event_time = normalize_datetime(event_time)
    hours = max((reference - event_time).total_seconds() / 3600.0, 0.0)
    return math.exp(-hours / 48.0)


def normalize_importance(value: float) -> float:
    return max(0.0, min(value, 1.0))


def pseudo_embedding(text: str, dimensions: int = 12) -> list[float]:
    counts = Counter(tokenize(text))
    if not counts:
        return [0.0] * dimensions
    total = sum(counts.values())
    vector = [0.0] * dimensions
    for token, count in counts.items():
        bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % dimensions
        vector[bucket] += count / total
    return vector
