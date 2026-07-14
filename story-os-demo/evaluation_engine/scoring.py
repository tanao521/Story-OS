"""Scoring deliberately ignores absent dimensions instead of treating them as zero."""
from __future__ import annotations

from typing import Iterable

from .models import DimensionScore


def weighted_score(dimensions: Iterable[DimensionScore]) -> tuple[float | None, float]:
    available = [item for item in dimensions if item.score is not None]
    if not available:
        return None, 0.0
    denominator = sum(item.weight for item in available)
    score = sum(float(item.score) * item.weight for item in available) / denominator
    confidence = sum(item.confidence * item.weight for item in available) / denominator
    return round(max(0.0, min(100.0, score)), 1), round(max(0.0, min(1.0, confidence)), 2)
