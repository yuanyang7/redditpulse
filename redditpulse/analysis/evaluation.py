"""Sentiment model evaluation against manual ground-truth labels."""

from .sentiment import sentiment_label, vader_compound

LABELS_ORDER = ["positive", "neutral", "negative"]


def predict(texts: list[str], model: str) -> list[str]:
    """Run a sentiment model over texts, returning one label per text."""
    if model == "vader":
        return [sentiment_label(vader_compound(t)) for t in texts]
    if model == "textblob":
        try:
            from textblob import TextBlob
        except ImportError:
            raise ImportError("textblob is not installed. Run: pip install textblob")
        preds = []
        for t in texts:
            pol = TextBlob(t).sentiment.polarity
            preds.append(sentiment_label(pol))
        return preds
    if model == "claude":
        from . import llm
        return llm.classify_sentiment_batch(texts)
    raise ValueError(f"Unknown model '{model}'. Supported: vader, textblob, claude")


def compute_metrics(gt: list[str], preds: list[str], model: str) -> dict:
    """Accuracy, per-class precision/recall/F1, and a confusion matrix."""
    correct = sum(g == p for g, p in zip(gt, preds))
    accuracy = correct / len(gt) if gt else 0.0

    per_class = {}
    for lbl in LABELS_ORDER:
        tp = sum(g == lbl and p == lbl for g, p in zip(gt, preds))
        fp = sum(g != lbl and p == lbl for g, p in zip(gt, preds))
        fn = sum(g == lbl and p != lbl for g, p in zip(gt, preds))
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else 0.0)
        per_class[lbl] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": gt.count(lbl),
        }

    matrix = {g: {p: 0 for p in LABELS_ORDER} for g in LABELS_ORDER}
    for g, p in zip(gt, preds):
        matrix[g][p] += 1

    return {
        "model": model,
        "total_labeled": len(gt),
        "accuracy": round(accuracy, 4),
        "per_class": per_class,
        "confusion_matrix": matrix,
        "labels_order": LABELS_ORDER,
    }
