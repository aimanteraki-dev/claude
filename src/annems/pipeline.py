"""AGENT 1 pipeline — the 06:00 MYT daily data pull. Pure code, no LLM.

Ref: CLAUDE.md Agent 1 + Metric Engine + principle 6 ("Fail loudly").

Order matters: entities first (so metrics have names to attach to), then
insights at all three levels, then GHL, then baselines. Each stage is isolated —
one failing source alerts and does not abort the others, because partial data
plus a loud alert beats no data and silence.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from . import db, notify
from .agents import analyst
from .collectors import ghl, meta
from .config import today_myt
from .metrics import compute_derived

log = logging.getLogger(__name__)


def sync_entities() -> dict[str, int]:
    """Refresh campaign/adset/ad names and statuses."""
    counts = {}
    counts["campaigns"] = db.upsert_campaigns(meta.fetch_campaigns())
    counts["adsets"] = db.upsert_adsets(meta.fetch_adsets())
    counts["ads"] = db.upsert_ads(meta.fetch_ads())
    return counts


def collect_insights(day: date) -> dict[str, int]:
    """Pull one day of insights at all three levels."""
    counts = {}
    for level in meta.LEVELS:
        rows = meta.fetch_insights(level, day)
        for row in rows:
            compute_derived(row)  # belt and braces; fetch_insights already does
        counts[level] = db.upsert_daily_metrics(rows)
    return counts


def collect_leads(day: date, lookback_days: int = 30) -> int:
    """Pull GHL leads and their pipeline stages."""
    rows = ghl.fetch_leads(since=day - timedelta(days=lookback_days))
    return db.upsert_leads(rows)


def run_daily(day: date | None = None, sync_entities_first: bool = True) -> dict:
    """The full 06:00 pull. Returns a summary dict; alerts on any failure.

    `day` defaults to yesterday: Meta's numbers for today are still moving, and
    a report built on a half-finished day is worse than no report.
    """
    day = day or (today_myt() - timedelta(days=1))
    summary: dict[str, object] = {"date": day.isoformat()}
    failures: list[str] = []

    with db.agent_run("agent_1_collector") as run_rec:
        if sync_entities_first:
            try:
                summary["entities"] = sync_entities()
            except Exception as exc:
                log.exception("Entity sync failed")
                failures.append("Meta entities")
                notify.alert_failure("Meta entity sync", exc)

        try:
            summary["insights"] = collect_insights(day)
        except Exception as exc:
            log.exception("Meta insights pull failed")
            failures.append("Meta insights")
            notify.alert_failure(f"Meta insights pull ({day})", exc)

        try:
            summary["leads"] = collect_leads(day)
        except Exception as exc:
            log.exception("GHL leads pull failed")
            failures.append("GHL leads")
            notify.alert_failure(f"GHL leads pull ({day})", exc)

        try:
            summary["baselines"] = analyst.persist_baselines(day)
        except Exception as exc:
            log.exception("Baseline computation failed")
            failures.append("Baselines")
            notify.alert_failure("Metric Engine baselines", exc)

        summary["failures"] = failures
        run_rec["summary"] = str(summary)[:1900]

    if failures:
        log.error("Daily pull completed with failures: %s", failures)
    else:
        log.info("Daily pull OK: %s", summary)
    return summary


def run_monitoring_pull(day: date | None = None) -> dict:
    """The lighter every-3-hours pull: today's numbers only, ad level.

    Used by Agent 3 so alerts fire on live data instead of yesterday's.
    """
    day = day or today_myt()
    summary: dict[str, object] = {"date": day.isoformat()}
    with db.agent_run("agent_1_monitor_pull") as run_rec:
        try:
            rows = meta.fetch_insights("ad", day)
            summary["ads"] = db.upsert_daily_metrics(rows)
        except Exception as exc:
            log.exception("Monitoring pull failed")
            notify.alert_failure(f"Monitoring pull ({day})", exc)
            summary["error"] = str(exc)[:300]
        run_rec["summary"] = str(summary)[:1900]
    return summary


def healthcheck() -> dict:
    """Cheap end-to-end check: can we reach Supabase, Meta, GHL and Telegram?"""
    results: dict[str, str] = {}

    try:
        db.get_client().table("agent_runs").select("id").limit(1).execute()
        results["supabase"] = "ok"
    except Exception as exc:
        results["supabase"] = f"FAIL: {str(exc)[:200]}"

    try:
        meta.fetch_campaigns()
        results["meta"] = "ok"
    except Exception as exc:
        results["meta"] = f"FAIL: {str(exc)[:200]}"

    try:
        ghl.fetch_leads(since=date.today() - timedelta(days=1))
        results["ghl"] = "ok"
    except Exception as exc:
        results["ghl"] = f"FAIL: {str(exc)[:200]}"

    try:
        notify.send("✅ Healthcheck: sistem Annems hidup.", to=notify.Recipient.AIMAN)
        results["telegram"] = "ok"
    except Exception as exc:
        results["telegram"] = f"FAIL: {str(exc)[:200]}"

    return results
