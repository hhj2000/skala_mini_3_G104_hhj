"""Auditable metrics without model or network dependencies."""
import math
import random
import statistics


def mean(values):
    values = list(values)
    return statistics.mean(values) if values else None


def retrieval_scores(predicted, relevant, k):
    """Binary relevance; no-answer queries are scored separately from positive recall."""
    if k < 1 or len(predicted) != len(set(predicted)):
        raise ValueError('k must be positive and returned IDs unique')
    ranked, gold = predicted[:k], set(relevant)
    hits = len(set(ranked) & gold)
    dcg = sum(1 / math.log2(i + 2) for i, x in enumerate(ranked) if x in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
    return {
        'precision_at_k': hits / k,
        'returned_precision': hits / len(ranked) if ranked else (0.0 if gold else 1.0),
        'recall_at_k': hits / len(gold) if gold else None,
        'mrr': next((1 / (i + 1) for i, x in enumerate(ranked) if x in gold), 0.0) if gold else None,
        'ndcg_at_k': dcg / ideal if ideal else None,
        'no_answer_correct': float(not ranked) if not gold else None,
        'exact_set': float(set(ranked) == gold),
    }


def classification_counts(predicted, expected, universe):
    pred, gold, universe = set(predicted), set(expected), set(universe)
    if not (pred | gold) <= universe:
        raise ValueError('Prediction or label outside evaluation universe')
    return dict(tp=len(pred & gold), fp=len(pred - gold), fn=len(gold - pred), tn=len(universe - (pred | gold)))


def classification_scores(counts):
    tp, fp, fn, tn = (counts[k] for k in ('tp', 'fp', 'fn', 'tn'))
    total = tp + fp + fn + tn
    return {**counts,
            'precision': tp / (tp + fp) if tp + fp else 0.0,
            'recall': tp / (tp + fn) if tp + fn else 0.0,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
            'accuracy': (tp + tn) / total if total else None,
            'specificity': tn / (tn + fp) if tn + fp else None}


def aggregate_classification(rows):
    return classification_scores({k: sum(r[k] for r in rows) for k in ('tp', 'fp', 'fn', 'tn')})


def bootstrap_delta(pairs, seed=104, samples=2000):
    """Case-level paired bootstrap. Repeats must be averaged per case beforehand."""
    values = [after - before for before, after in pairs]
    if not values:
        return None
    rng = random.Random(seed)
    draws = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(samples))
    return {'after_minus_before': statistics.mean(values),
            'ci95': [draws[int(.025 * (samples - 1))], draws[int(.975 * (samples - 1))]],
            'paired_cases': len(values), 'resamples': samples, 'seed': seed}


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    return values[max(0, math.ceil(p * len(values)) - 1)]
