"""Reusable building blocks for features — time decay, weighted averages.

Pure functions only. Features compose these into domain-specific
computations. Stays numpy-free so the unit tests stay obvious in code
review and the import graph stays light.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date


def exponential_decay_weight(days_ago: int, half_life_days: float) -> float:
    """Exponential time decay: ``2^(-days_ago / half_life_days)``.

    At ``days_ago == 0`` the weight is 1.0; at the half-life it's 0.5.
    Negative ``days_ago`` (a round "in the future" relative to the as-of
    date) is clamped to 0 so the weight stays in ``[0, 1]``.

    Half-life of 60–90 days is the standard range for golf form per
    doc 02 §3.
    """
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    days = max(days_ago, 0)
    return math.pow(2.0, -days / half_life_days)


def weighted_mean(
    values: Iterable[float],
    weights: Iterable[float],
) -> float:
    """Weighted arithmetic mean. Returns 0.0 when the total weight is zero."""
    total_value = 0.0
    total_weight = 0.0
    for value, weight in zip(values, weights, strict=True):
        total_value += value * weight
        total_weight += weight
    if total_weight == 0.0:
        return 0.0
    return total_value / total_weight


def days_between(earlier: date, later: date) -> int:
    """Calendar-day difference. Negative if ``later`` is before ``earlier``."""
    return (later - earlier).days
