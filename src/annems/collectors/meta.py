"""Meta Marketing API (Insights) collector — READ ONLY.

Ref: CLAUDE.md Agent 1 + section 6 ("V1 does NOT write to Meta at all").
This module must never call a POST/DELETE endpoint. Publishing, pausing and
budget changes stay manual in Ads Manager.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import get_settings
from ..metrics import MetricRow, compute_derived

log = logging.getLogger(__name__)

LEVELS = ("campaign", "adset", "ad")

INSIGHT_FIELDS = [
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "spend",
    "impressions",
    "clicks",
    "reach",
    "frequency",
    "actions",
]

# Meta reports leads under several action_type names depending on how the
# conversion is set up (native lead form vs pixel vs CAPI). Count any of them.
LEAD_ACTION_TYPES = {
    "lead",
    "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead",
    "leadgen.other",
    "onsite_web_lead",
}

ID_FIELD = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}


class MetaAPIError(RuntimeError):
    pass


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def _get(path: str, params: dict[str, Any]) -> dict:
    s = get_settings()
    url = f"{s.meta_graph_base}/{path.lstrip('/')}"
    params = {**params, "access_token": s.meta_access_token}
    with httpx.Client(timeout=60) as client:
        resp = client.get(url, params=params)
    if resp.status_code >= 400:
        raise MetaAPIError(f"{resp.status_code} on {path}: {resp.text[:500]}")
    return resp.json()


def _paginate(path: str, params: dict[str, Any]) -> Iterator[dict]:
    """Follow Meta's cursor pagination until exhausted."""
    page = _get(path, params)
    while True:
        yield from page.get("data", [])
        next_url = (page.get("paging") or {}).get("next")
        if not next_url:
            return
        with httpx.Client(timeout=60) as client:
            resp = client.get(next_url)
        if resp.status_code >= 400:
            raise MetaAPIError(f"{resp.status_code} on pagination: {resp.text[:500]}")
        page = resp.json()


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------


def fetch_insights(level: str, day: date) -> list[MetricRow]:
    """One day of insights at one level. Derived metrics computed locally."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")

    s = get_settings()
    params = {
        "level": level,
        "fields": ",".join(INSIGHT_FIELDS),
        "time_range": f'{{"since":"{day.isoformat()}","until":"{day.isoformat()}"}}',
        "time_increment": 1,
        "limit": 500,
    }
    rows: list[MetricRow] = []
    for item in _paginate(f"{s.ad_account}/insights", params):
        ref_id = item.get(ID_FIELD[level])
        if not ref_id:
            continue
        row = MetricRow(
            date=day,
            level=level,
            ref_id=str(ref_id),
            spend=_num(item.get("spend")),
            impressions=int(_num(item.get("impressions"))),
            clicks=int(_num(item.get("clicks"))),
            reach=int(_num(item.get("reach"))),
            frequency=_num(item.get("frequency")),
            leads=count_leads(item.get("actions")),
        )
        rows.append(compute_derived(row))
    log.info("meta insights %s %s: %d rows", level, day, len(rows))
    return rows


def count_leads(actions: list[dict] | None) -> int:
    """Sum lead conversions across Meta's several lead action_type names."""
    if not actions:
        return 0
    return int(
        sum(
            _num(a.get("value"))
            for a in actions
            if a.get("action_type") in LEAD_ACTION_TYPES
        )
    )


def _num(value: Any) -> float:
    """Meta returns numbers as strings, and omits fields that are zero."""
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Entities (names, statuses, structure)
# ---------------------------------------------------------------------------


def fetch_campaigns() -> list[dict]:
    s = get_settings()
    params = {"fields": "id,name,objective,status", "limit": 200}
    return [
        {
            "meta_campaign_id": c["id"],
            "name": c.get("name", ""),
            "objective": c.get("objective"),
            "status": c.get("status"),
        }
        for c in _paginate(f"{s.ad_account}/campaigns", params)
    ]


def fetch_adsets() -> list[dict]:
    s = get_settings()
    params = {"fields": "id,name,campaign_id,status,targeting", "limit": 200}
    out = []
    for a in _paginate(f"{s.ad_account}/adsets", params):
        out.append(
            {
                "meta_adset_id": a["id"],
                "campaign_id": a.get("campaign_id"),
                "name": a.get("name", ""),
                "audience_desc": _describe_audience(a.get("targeting")),
                "status": a.get("status"),
            }
        )
    return out


def fetch_ads() -> list[dict]:
    s = get_settings()
    params = {"fields": "id,name,adset_id,status", "limit": 500}
    return [
        {
            "meta_ad_id": a["id"],
            "adset_id": a.get("adset_id"),
            "name": a.get("name", ""),
            "status": a.get("status"),
        }
        for a in _paginate(f"{s.ad_account}/ads", params)
    ]


def _describe_audience(targeting: dict | None) -> str:
    """Flatten Meta's targeting blob into one human-readable line.

    The analyst needs 'who was this shown to' in words; the raw JSON is too
    noisy to put in a prompt.
    """
    if not targeting:
        return ""
    parts = []
    if (age_min := targeting.get("age_min")) and (age_max := targeting.get("age_max")):
        parts.append(f"umur {age_min}-{age_max}")
    if geo := targeting.get("geo_locations"):
        countries = geo.get("countries") or []
        regions = [r.get("name") for r in (geo.get("regions") or []) if r.get("name")]
        if countries:
            parts.append("/".join(countries))
        if regions:
            parts.append(", ".join(regions[:3]))
    interests = [
        i.get("name")
        for spec in (targeting.get("flexible_spec") or [])
        for i in (spec.get("interests") or [])
        if i.get("name")
    ]
    if interests:
        parts.append("minat: " + ", ".join(interests[:5]))
    if targeting.get("custom_audiences"):
        parts.append(f"{len(targeting['custom_audiences'])} custom audience")
    return " · ".join(parts)
