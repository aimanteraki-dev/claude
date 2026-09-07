"""Shared test fixtures.

These tests deliberately touch no network and no database: the parts of the
system that decide anything (the metric engine, the alert rules, the tagging
log validator) are pure functions, and that is exactly why they are testable.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from annems.config import get_thresholds
from annems.metrics import MetricRow, compute_derived

TODAY = date(2026, 9, 7)


@pytest.fixture
def cfg() -> dict:
    """The real config/thresholds.yaml — tests must break if it drifts."""
    return get_thresholds()


def make_row(
    day: date,
    ref_id: str = "ad_1",
    spend: float = 100.0,
    impressions: int = 10_000,
    clicks: int = 200,
    leads: int = 10,
    reach: int = 8_000,
    frequency: float = 1.25,
    level: str = "ad",
) -> MetricRow:
    """A metric row with derived values already computed."""
    return compute_derived(
        MetricRow(
            date=day,
            level=level,
            ref_id=ref_id,
            spend=spend,
            impressions=impressions,
            clicks=clicks,
            leads=leads,
            reach=reach,
            frequency=frequency,
        )
    )


def make_history(
    days: int = 10,
    end: date = TODAY,
    ref_id: str = "ad_1",
    **row_kwargs,
) -> list[MetricRow]:
    """A steady run of identical days ending the day BEFORE `end`.

    Steady history means any breach a test injects on `end` is unambiguous.
    """
    return [
        make_row(end - timedelta(days=i), ref_id=ref_id, **row_kwargs)
        for i in range(1, days + 1)
    ]
