"""GoHighLevel collector — leads and pipeline stages.

Ref: CLAUDE.md Agent 1. This feeds CPQL, the metric that separates a cheap lead
from a lead worth having.

Honesty note: attribution here is only as good as GHL's own attribution data.
Where GHL gives us no ad id, source_ad_id is None and that lead is counted in
account-level CPQL but not attributed to any single ad. Never guess.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Any, Iterator

import httpx
import yaml
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import REPO_ROOT, get_settings

log = logging.getLogger(__name__)

GHL_API_VERSION = "2021-07-28"
STAGE_MAP_PATH = REPO_ROOT / "config" / "ghl_stages.yaml"
CANONICAL_STAGES = ("new", "qualified", "appointment", "closed_won", "closed_lost")


class GHLAPIError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def stage_lookup() -> dict[str, str]:
    """Flatten the YAML map into {lowercased GHL stage name: canonical stage}."""
    with STAGE_MAP_PATH.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    lookup: dict[str, str] = {}
    for canonical, names in raw.items():
        if canonical not in CANONICAL_STAGES:
            raise ValueError(f"Unknown canonical stage in ghl_stages.yaml: {canonical}")
        for name in names or []:
            lookup[str(name).strip().lower()] = canonical
    return lookup


def normalise_stage(ghl_stage_name: str | None) -> str:
    """Map a GHL stage name to a canonical stage, defaulting to 'new'."""
    if not ghl_stage_name:
        return "new"
    key = str(ghl_stage_name).strip().lower()
    mapped = stage_lookup().get(key)
    if mapped is None:
        log.warning(
            "Unmapped GHL stage %r -> counted as 'new'. Add it to config/ghl_stages.yaml.",
            ghl_stage_name,
        )
        return "new"
    return mapped


def _headers() -> dict[str, str]:
    s = get_settings()
    return {
        "Authorization": f"Bearer {s.ghl_api_key}",
        "Version": GHL_API_VERSION,
        "Accept": "application/json",
    }


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def _get(path: str, params: dict[str, Any]) -> dict:
    s = get_settings()
    url = f"{s.ghl_api_base.rstrip('/')}/{path.lstrip('/')}"
    with httpx.Client(timeout=60) as client:
        resp = client.get(url, params=params, headers=_headers())
    if resp.status_code >= 400:
        raise GHLAPIError(f"{resp.status_code} on {path}: {resp.text[:500]}")
    return resp.json()


def _paginate_opportunities(since: date) -> Iterator[dict]:
    s = get_settings()
    page = 1
    while True:
        data = _get(
            "opportunities/search",
            {
                "location_id": s.ghl_location_id,
                "date": since.isoformat(),
                "limit": 100,
                "page": page,
            },
        )
        opportunities = data.get("opportunities") or []
        if not opportunities:
            return
        yield from opportunities
        meta = data.get("meta") or {}
        if not meta.get("nextPageUrl") and len(opportunities) < 100:
            return
        page += 1
        if page > 100:  # hard stop; 10k records is far beyond expected volume
            log.warning("GHL pagination hit the 100-page guard rail")
            return


def fetch_leads(since: date | None = None, lookback_days: int = 30) -> list[dict]:
    """Leads with their current pipeline stage, ready for the `leads` table."""
    since = since or (date.today() - timedelta(days=lookback_days))
    rows: list[dict] = []
    for opp in _paginate_opportunities(since):
        contact = opp.get("contact") or {}
        contact_id = opp.get("contactId") or contact.get("id")
        if not contact_id:
            continue
        rows.append(
            {
                "ghl_contact_id": str(contact_id),
                "source_ad_id": extract_ad_id(contact, opp),
                "stage": normalise_stage(opp.get("pipelineStageName") or opp.get("stageName")),
                "stage_updated_at": _iso(opp.get("updatedAt")),
                "created_at": _iso(opp.get("createdAt")) or datetime.now().isoformat(),
            }
        )
    log.info("ghl leads since %s: %d rows", since, len(rows))
    return rows


def extract_ad_id(contact: dict, opportunity: dict | None = None) -> str | None:
    """Best-effort ad attribution from GHL's attribution blob.

    Returns None rather than guessing when GHL has no ad id — an unattributed
    lead is better than a lead attributed to the wrong ad.
    """
    sources = []
    for holder in (contact, opportunity or {}):
        attribution = holder.get("attributionSource") or holder.get("attributions")
        if isinstance(attribution, dict):
            sources.append(attribution)
        elif isinstance(attribution, list):
            sources.extend(a for a in attribution if isinstance(a, dict))

    for src in sources:
        for key in ("adId", "ad_id", "fbAdId", "utmAdId"):
            value = src.get(key)
            if value:
                return str(value)
        # Some setups only pass the ad id through utm_content.
        content = src.get("utmContent") or src.get("utm_content")
        if content and str(content).isdigit():
            return str(content)
    return None


def _iso(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, (int, float)):  # epoch millis
        return datetime.utcfromtimestamp(value / 1000).isoformat()
    return str(value)
