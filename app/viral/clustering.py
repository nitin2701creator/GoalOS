"""Deduplication and clustering for the Viral Idea Finder.

Groups related content items into clusters using lightweight local
techniques: normalized title comparison, keyword overlap, and
Jaccard similarity on word sets.  No external ML dependencies.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(text: str) -> set[str]:
    """Split normalized text into a set of non-trivial words."""
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "under", "and", "but",
        "or", "nor", "not", "so", "yet", "both", "either", "neither", "each",
        "every", "all", "any", "few", "more", "most", "other", "some", "such",
        "no", "only", "own", "same", "than", "too", "very", "just", "this",
        "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
        "you", "your", "he", "him", "his", "she", "her", "they", "them", "their",
        "what", "which", "who", "whom",
    }
    words = _normalize(text).split()
    return {w for w in words if len(w) > 2 and w not in stop_words}


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two word sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def compute_title_similarity(title_a: str, title_b: str) -> float:
    """Compute similarity between two titles using token overlap."""
    tokens_a = _tokenize(title_a)
    tokens_b = _tokenize(title_b)
    return jaccard_similarity(tokens_a, tokens_b)


def compute_content_similarity(desc_a: str, desc_b: str) -> float:
    """Compute similarity between two descriptions using keyword overlap."""
    tokens_a = _tokenize(desc_a)
    tokens_b = _tokenize(desc_b)
    return jaccard_similarity(tokens_a, tokens_b)


def cluster_items(
    items: list[dict[str, Any]],
    title_threshold: float = 0.45,
    content_threshold: float = 0.30,
) -> list[list[int]]:
    """Group similar items into clusters.

    Each cluster is a list of indices into the ``items`` list.
    Two items are merged when their title OR content similarity
    exceeds the respective threshold.

    Returns a list of clusters (each cluster is a list of item indices).
    """
    n = len(items)
    if n == 0:
        return []

    # Pre-compute titles and descriptions
    titles = [_normalize(it.get("title", "")) for it in items]
    descriptions = [_normalize(it.get("description", "")) for it in items]

    # Union-Find for clustering
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # Pairwise comparison (OK for hundreds of items)
    for i in range(n):
        for j in range(i + 1, n):
            title_sim = compute_title_similarity(titles[i], titles[j])
            if title_sim >= title_threshold:
                union(i, j)
                continue
            content_sim = compute_content_similarity(descriptions[i], descriptions[j])
            if content_sim >= content_threshold:
                union(i, j)

    # Collect clusters
    clusters_map: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters_map[find(i)].append(i)

    return list(clusters_map.values())
