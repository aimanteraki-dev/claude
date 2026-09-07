"""THE METRIC ENGINE — pure code. No LLM touches any number in this file.

Ref: CLAUDE.md principle 2 ("LLMs never do math") and section 4 (Metric Engine).
Every metric an agent ever quotes is computed here first and passed in as data.

Conventions, fixed once so reports never contradict each other:
    CTR  = clicks / impressions * 100        (percent)
    CPM  = spend / impressions * 1000        (RM per 1000 impressions)
    CPC  = spend / clicks                    (RM)
    CPL  = spend / leads                     (RM)
    CVR  = leads / clicks * 100              (percent)
    CPQL = spend / qualified_leads           (RM; qualified = GHL stage qualified or later)

Any metric whose denominator is zero is None — never 0, never infinity.
None means "cannot be computed", and downstream code must say so rather than
pretending the value is zero.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Iterable, Sequence

# Stages that count as "qualified or later" for CPQL.
QUALIFIED_STAGES = {"qualified", "appointment", "closed_won"}
ALL_STAGES = {"new", "qualified", "appointment", "closed_won", "closed_lost"}

DERIVED_METRICS = ("cpl", "ctr", "cpm", "cpc", "cvr")


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Division that returns None instead of raising or faking a zero."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def round_or_none(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


@dataclass
class MetricRow:
    """One day of raw + derived metrics for one campaign / adset / ad."""

    date: date
    level: str  # campaign | adset | ad
    ref_id: str
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    reach: int = 0
    frequency: float = 0.0
    leads: int = 0

    # Derived — filled by compute_derived(), never set by hand.
    cpl: float | None = None
    ctr: float | None = None
    cpm: float | None = None
    cpc: float | None = None
    cvr: float | None = None

    def to_db(self) -> dict:
        row = asdict(self)
        row["date"] = self.date.isoformat()
        return row


def compute_derived(row: MetricRow) -> MetricRow:
    """Fill the five derived metrics on a row. Idempotent."""
    row.ctr = round_or_none(_pct(safe_div(row.clicks, row.impressions)), 4)
    row.cpm = round_or_none(
        None if row.impressions == 0 else row.spend / row.impressions * 1000, 4
    )
    row.cpc = round_or_none(safe_div(row.spend, row.clicks), 4)
    row.cpl = round_or_none(safe_div(row.spend, row.leads), 2)
    row.cvr = round_or_none(_pct(safe_div(row.leads, row.clicks)), 4)
    return row


def _pct(ratio: float | None) -> float | None:
    return None if ratio is None else ratio * 100


def compute_cpql(spend: float, qualified_leads: int) -> float | None:
    """CPQL = spend / qualified leads. The number that actually matters."""
    return round_or_none(safe_div(spend, qualified_leads), 2)


def count_qualified(stages: Iterable[str]) -> int:
    """How many leads reached 'qualified' or later."""
    return sum(1 for s in stages if (s or "").strip().lower() in QUALIFIED_STAGES)


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


@dataclass
class Baseline:
    level: str
    ref_id: str
    metric: str
    date: date
    value: float | None       # the value on `date`
    avg_7d: float | None      # mean of the 7 days BEFORE `date`
    avg_14d: float | None
    delta_pct: float | None   # % change of value vs avg_7d
    days_of_data: int = 0

    def to_db(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "level": self.level,
            "ref_id": self.ref_id,
            "metric": self.metric,
            "avg_7d": self.avg_7d,
            "avg_14d": self.avg_14d,
            "delta_pct": self.delta_pct,
        }


def moving_average(values: Sequence[float | None]) -> float | None:
    """Mean of the values that exist. None-only or empty input -> None.

    Missing days are skipped rather than counted as zero: an ad that ran on
    3 of 7 days has a 3-day average, not a 7-day average diluted by four zeros.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def pct_change(current: float | None, baseline: float | None) -> float | None:
    """Percent change of current vs baseline. None if either side is unusable."""
    if current is None or baseline in (None, 0):
        return None
    return (current - baseline) / baseline * 100


def compute_baseline(
    history: Sequence[MetricRow],
    metric: str,
    as_of: date,
    level: str,
    ref_id: str,
) -> Baseline:
    """Baseline for one metric on one ref, as of a given date.

    `history` may contain any dates; only rows strictly BEFORE `as_of` feed the
    averages, so today's number is never compared against itself.
    """
    if metric not in DERIVED_METRICS and metric not in {"spend", "leads", "frequency"}:
        raise ValueError(f"Unknown metric for baseline: {metric}")

    by_date = {r.date: r for r in history if r.level == level and r.ref_id == ref_id}
    current_row = by_date.get(as_of)
    value = getattr(current_row, metric) if current_row else None

    def window(days: int) -> list[float | None]:
        return [
            getattr(by_date[d], metric)
            for i in range(1, days + 1)
            if (d := as_of - timedelta(days=i)) in by_date
        ]

    prior_7 = window(7)
    prior_14 = window(14)
    avg_7d = moving_average(prior_7)
    avg_14d = moving_average(prior_14)

    return Baseline(
        level=level,
        ref_id=ref_id,
        metric=metric,
        date=as_of,
        value=round_or_none(value, 4),
        avg_7d=round_or_none(avg_7d, 4),
        avg_14d=round_or_none(avg_14d, 4),
        delta_pct=round_or_none(pct_change(value, avg_7d), 2),
        days_of_data=len([v for v in prior_7 if v is not None]),
    )


def compute_all_baselines(
    history: Sequence[MetricRow],
    as_of: date,
    metrics: Sequence[str] = DERIVED_METRICS,
) -> list[Baseline]:
    """Baselines for every (level, ref_id, metric) present in history."""
    refs = {(r.level, r.ref_id) for r in history}
    out: list[Baseline] = []
    for level, ref_id in sorted(refs):
        for metric in metrics:
            out.append(compute_baseline(history, metric, as_of, level, ref_id))
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@dataclass
class Totals:
    """Rolled-up totals over a set of rows. Derived metrics are recomputed from
    the summed raw numbers — never averaged from per-row derived values, which
    would silently weight a RM5 ad the same as a RM500 ad."""

    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    leads: int = 0
    reach: int = 0
    qualified_leads: int = 0
    cpl: float | None = None
    ctr: float | None = None
    cpm: float | None = None
    cpc: float | None = None
    cvr: float | None = None
    cpql: float | None = None
    days: int = 0
    refs: int = 0
    dates: list[str] = field(default_factory=list)


def aggregate(rows: Iterable[MetricRow], qualified_leads: int = 0) -> Totals:
    rows = list(rows)
    t = Totals()
    for r in rows:
        t.spend += r.spend
        t.impressions += r.impressions
        t.clicks += r.clicks
        t.leads += r.leads
        t.reach += r.reach
    t.spend = round(t.spend, 2)
    t.qualified_leads = qualified_leads
    t.days = len({r.date for r in rows})
    t.refs = len({(r.level, r.ref_id) for r in rows})
    t.dates = sorted({r.date.isoformat() for r in rows})

    scratch = MetricRow(
        date=rows[0].date if rows else date.min,
        level="agg",
        ref_id="agg",
        spend=t.spend,
        impressions=t.impressions,
        clicks=t.clicks,
        leads=t.leads,
    )
    compute_derived(scratch)
    t.cpl, t.ctr, t.cpm, t.cpc, t.cvr = scratch.cpl, scratch.ctr, scratch.cpm, scratch.cpc, scratch.cvr
    t.cpql = compute_cpql(t.spend, qualified_leads)
    return t


def rank_ads(
    rows: Iterable[MetricRow],
    metric: str = "cpl",
    lowest_is_best: bool = True,
    min_spend: float = 0.0,
) -> list[MetricRow]:
    """Rank rows by a metric, dropping rows where it could not be computed.

    Ads below `min_spend` are excluded — a single cheap lead on RM8 of spend is
    noise, and ranking it first would send Aiman chasing a phantom winner.
    """
    usable = [
        r for r in rows if getattr(r, metric) is not None and r.spend >= min_spend
    ]
    return sorted(usable, key=lambda r: getattr(r, metric), reverse=not lowest_is_best)
