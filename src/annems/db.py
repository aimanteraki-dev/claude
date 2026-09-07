"""Supabase access layer. Every read/write to Postgres goes through here.

Ref: CLAUDE.md section 5 (schema) and section 8 (every agent run logged).
Kept deliberately boring: thin wrappers, explicit SQL-ish calls, no ORM.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Iterable, Iterator, Sequence

from .config import get_settings, now_myt
from .metrics import MetricRow

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client():
    """Supabase client, created once per process."""
    from supabase import create_client  # imported lazily so tests need no network

    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_key)


# ---------------------------------------------------------------------------
# agent_runs — audit trail for every scheduled job
# ---------------------------------------------------------------------------


@contextmanager
def agent_run(agent: str) -> Iterator[dict]:
    """Log an agent run start->finish, recording errors before re-raising.

    Usage:
        with agent_run("agent_1_collector") as run:
            ...
            run["summary"] = "42 rows"
    """
    run: dict[str, Any] = {"summary": "", "id": None}
    started = now_myt()
    try:
        res = (
            get_client()
            .table("agent_runs")
            .insert({"agent": agent, "started_at": started.isoformat(), "status": "running"})
            .execute()
        )
        run["id"] = res.data[0]["id"] if res.data else None
    except Exception:  # a broken audit table must not stop the actual work
        log.exception("Could not open agent_runs record for %s", agent)

    try:
        yield run
    except Exception as exc:
        _close_run(run.get("id"), "error", str(exc)[:2000], run.get("summary", ""))
        raise
    else:
        _close_run(run.get("id"), "ok", None, run.get("summary", ""))


def _close_run(run_id: str | None, status: str, error: str | None, summary: str) -> None:
    if not run_id:
        return
    try:
        get_client().table("agent_runs").update(
            {
                "finished_at": now_myt().isoformat(),
                "status": status,
                "error": error,
                "output_summary": (summary or "")[:2000],
            }
        ).eq("id", run_id).execute()
    except Exception:
        log.exception("Could not close agent_runs record %s", run_id)


# ---------------------------------------------------------------------------
# Entity upserts
# ---------------------------------------------------------------------------


def upsert_campaigns(rows: Sequence[dict]) -> int:
    return _upsert("campaigns", rows, "meta_campaign_id")


def upsert_adsets(rows: Sequence[dict]) -> int:
    return _upsert("adsets", rows, "meta_adset_id")


def upsert_ads(rows: Sequence[dict]) -> int:
    return _upsert("ads", rows, "meta_ad_id")


def upsert_daily_metrics(rows: Sequence[MetricRow]) -> int:
    payload = [r.to_db() for r in rows]
    return _upsert("daily_metrics", payload, "date,level,ref_id")


def upsert_baselines(rows: Sequence[dict]) -> int:
    return _upsert("computed_baselines", rows, "date,level,ref_id,metric")


def upsert_leads(rows: Sequence[dict]) -> int:
    return _upsert("leads", rows, "ghl_contact_id")


def _upsert(table: str, rows: Sequence[dict], on_conflict: str) -> int:
    rows = list(rows)
    if not rows:
        return 0
    written = 0
    for chunk in _chunks(rows, 500):
        get_client().table(table).upsert(chunk, on_conflict=on_conflict).execute()
        written += len(chunk)
    log.info("upsert %s: %d rows", table, written)
    return written


def _chunks(seq: Sequence[dict], size: int) -> Iterable[Sequence[dict]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def fetch_metric_history(
    level: str, start: date, end: date, ref_ids: Sequence[str] | None = None
) -> list[MetricRow]:
    """All daily_metrics rows for a level between two dates, inclusive."""
    q = (
        get_client()
        .table("daily_metrics")
        .select("*")
        .eq("level", level)
        .gte("date", start.isoformat())
        .lte("date", end.isoformat())
    )
    if ref_ids:
        q = q.in_("ref_id", list(ref_ids))
    res = q.execute()
    return [_row_to_metric(r) for r in (res.data or [])]


def fetch_window(level: str, as_of: date, days: int = 14) -> list[MetricRow]:
    """History ending at `as_of`, long enough to compute 7d and 14d baselines."""
    return fetch_metric_history(level, as_of - timedelta(days=days), as_of)


def _row_to_metric(r: dict) -> MetricRow:
    return MetricRow(
        date=date.fromisoformat(r["date"]),
        level=r["level"],
        ref_id=r["ref_id"],
        spend=float(r.get("spend") or 0),
        impressions=int(r.get("impressions") or 0),
        clicks=int(r.get("clicks") or 0),
        reach=int(r.get("reach") or 0),
        frequency=float(r.get("frequency") or 0),
        leads=int(r.get("leads") or 0),
        cpl=_maybe_float(r.get("cpl")),
        ctr=_maybe_float(r.get("ctr")),
        cpm=_maybe_float(r.get("cpm")),
        cpc=_maybe_float(r.get("cpc")),
        cvr=_maybe_float(r.get("cvr")),
    )


def _maybe_float(v: Any) -> float | None:
    return None if v is None else float(v)


def fetch_ad_names() -> dict[str, str]:
    """meta_ad_id -> ad name, so reports read as names not IDs."""
    res = get_client().table("ads").select("meta_ad_id,name").execute()
    return {r["meta_ad_id"]: r["name"] for r in (res.data or [])}


def fetch_leads_since(since: date) -> list[dict]:
    res = (
        get_client()
        .table("leads")
        .select("*")
        .gte("created_at", since.isoformat())
        .execute()
    )
    return res.data or []


def count_qualified_since(since: date) -> int:
    """Qualified-or-later leads created since a date — the CPQL denominator."""
    from .metrics import QUALIFIED_STAGES

    res = (
        get_client()
        .table("leads")
        .select("id,stage", count="exact")
        .gte("created_at", since.isoformat())
        .in_("stage", sorted(QUALIFIED_STAGES))
        .execute()
    )
    if res.count is not None:
        return int(res.count)
    return len(res.data or [])


# ---------------------------------------------------------------------------
# Alerts, creatives, approvals
# ---------------------------------------------------------------------------


def record_alert(rule: str, severity: str, message: str, ref_id: str | None = None) -> None:
    try:
        get_client().table("alerts").insert(
            {
                "rule": rule,
                "severity": severity,
                "message": message[:4000],
                "ref_id": ref_id,
                "sent_at": now_myt().isoformat(),
            }
        ).execute()
    except Exception:
        log.exception("Could not record alert %s", rule)


def recent_alert_exists(rule: str, ref_id: str | None, within_hours: int) -> bool:
    """Cooldown check, so a single sick ad does not alert every three hours."""
    cutoff = now_myt() - timedelta(hours=within_hours)
    q = (
        get_client()
        .table("alerts")
        .select("id")
        .eq("rule", rule)
        .gte("sent_at", cutoff.isoformat())
        .limit(1)
    )
    if ref_id:
        q = q.eq("ref_id", ref_id)
    res = q.execute()
    return bool(res.data)


def insert_creative(payload: dict) -> str | None:
    res = get_client().table("creatives").insert(payload).execute()
    return res.data[0]["id"] if res.data else None


def request_approval(item_type: str, item_id: str) -> str | None:
    """Open an approval record. Nothing acts on the item until a human decides.

    Ref: CLAUDE.md section 6. V1 never writes to Meta at all, so this is a
    record of intent, not a trigger.
    """
    res = (
        get_client()
        .table("approvals")
        .insert({"item_type": item_type, "item_id": item_id})
        .execute()
    )
    return res.data[0]["id"] if res.data else None


def decide_approval(approval_id: str, decision: str, decided_by: str) -> None:
    get_client().table("approvals").update(
        {
            "decision": decision,
            "decided_by": decided_by,
            "decided_at": now_myt().isoformat(),
        }
    ).eq("id", approval_id).execute()
