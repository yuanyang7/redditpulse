"""Semantic relevance scoring using sentence-transformers embeddings."""

import numpy as np
from sentence_transformers import SentenceTransformer

_model = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def score_relevance(topic: str, comments: list[dict], key: str = "body") -> list[float]:
    """Return cosine similarity scores between topic and each comment.

    Args:
        topic: The topic string to compare against.
        comments: List of comment dicts.
        key: Dict key containing the text to score.

    Returns:
        List of float scores in [0, 1], one per comment.
    """
    if not comments:
        return []

    model = _get_model()
    topic_emb = model.encode([topic], normalize_embeddings=True)
    texts = [c[key] for c in comments]
    comment_embs = model.encode(texts, normalize_embeddings=True, batch_size=64)

    scores = np.dot(comment_embs, topic_emb.T).flatten().tolist()
    return scores


def filter_by_relevance(
    topic: str,
    comments: list[dict],
    threshold: float = 0.3,
    key: str = "body",
) -> list[dict]:
    """Filter comments keeping only those above the relevance threshold.

    Args:
        topic: The topic string.
        comments: List of comment dicts.
        threshold: Minimum cosine similarity to keep (0.0-1.0).
        key: Dict key containing the text to score.

    Returns:
        Filtered list of comment dicts.
    """
    if not comments:
        return []

    scores = score_relevance(topic, comments, key=key)
    return [c for c, s in zip(comments, scores) if s >= threshold]
