"""REPORTER — the 07:00 MYT daily Telegram message (part of Agent 2's run).

Ref: CLAUDE.md section 4 (Reporter spec) + Milestone 2.

Every figure in the message is formatted from pre-computed values. The LLM's
only contribution is the diagnosis paragraph produced by the analyst.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from .. import db, notify
from ..config import get_thresholds, today_myt
from ..metrics import aggregate, rank_ads
from .analyst import DataPack, analyse

log = logging.getLogger(__name__)


def rm(value: float | None, digits: int = 2) -> str:
    """Currency, or an honest dash. Never prints RM0.00 for missing data."""
    if value is None:
        return "—"
    return f"RM{value:,.{digits}f}"


def pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}%"


def num(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}"


def delta_arrow(value: float | None) -> str:
    """Direction marker for a percent change, blank when unknown."""
    if value is None:
        return ""
    if value > 0:
        return f" (▲{value:.0f}%)"
    if value < 0:
        return f" (▼{abs(value):.0f}%)"
    return " (0%)"


def build_daily_report(as_of: date, diagnosis: str, pack: DataPack) -> str:
    """Compose the morning message. Pure formatting — no math beyond rounding."""
    y = pack.semalam
    w = pack.tujuh_hari

    lines = [
        f"*LAPORAN PAGI ANNEMS* — {as_of.strftime('%d %b %Y')}",
        "",
        "*Semalam*",
        f"• Spend: {rm(y['spend_rm'])}",
        f"• Lead: {num(y['leads'])}",
        f"• CPL: {rm(y['cpl_rm'])}",
        f"• CTR: {pct(y['ctr_pct'])}",
        f"• Klik: {num(y['clicks'])}  ·  Impression: {num(y['impressions'])}",
        "",
        "*7 hari*",
        f"• Spend: {rm(w['spend_rm'])}",
        f"• Lead: {num(w['leads'])}  ·  Qualified: {num(pack.qualified_leads_7d)}",
        f"• CPL: {rm(w['cpl_rm'])}  ·  *CPQL: {rm(pack.cpql_7d)}*",
    ]

    if pack.ads_terbaik:
        b = pack.ads_terbaik[0]
        lines += [
            "",
            "*Ad terbaik (CPL terendah)*",
            f"• {b['nama']}",
            f"  {rm(b['spend_rm'])} → {num(b['leads'])} lead · CPL {rm(b['cpl_rm'])}",
        ]
    if pack.ads_terlemah:
        w_ad = pack.ads_terlemah[0]
        lines += [
            "",
            "*Ad terlemah (CPL tertinggi)*",
            f"• {w_ad['nama']}",
            f"  {rm(w_ad['spend_rm'])} → {num(w_ad['leads'])} lead · CPL {rm(w_ad['cpl_rm'])}",
        ]

    if pack.nota_kualiti_data:
        lines += ["", "*⚠️ Nota data*"]
        lines += [f"• {n}" for n in pack.nota_kualiti_data]

    lines += ["", "*Diagnosis*", diagnosis.strip()]
    return "\n".join(lines)


def run_daily(as_of: date | None = None, to: str = notify.Recipient.BOTH) -> str:
    """Compose and send the morning report. Returns the message text."""
    as_of = as_of or (today_myt() - timedelta(days=1))
    with db.agent_run("reporter_daily") as run:
        diagnosis, pack = analyse(as_of)
        message = build_daily_report(as_of, diagnosis, pack)
        notify.send(message, to=to)
        run["summary"] = (
            f"{as_of} spend={pack.semalam['spend_rm']} leads={pack.semalam['leads']} "
            f"cpql={pack.cpql_7d}"
        )
    return message


# ---------------------------------------------------------------------------
# Weekly summary (Mondays)
# ---------------------------------------------------------------------------

WEEKLY_SYSTEM = """Kau Performance Analyst untuk Annems Leadership Solution.

Semua nombor dalam input SUDAH DIKIRA. Jangan kira apa-apa sendiri, jangan reka
nombor, jangan sebut nombor yang tiada dalam input.

Tulis ringkasan mingguan dalam Bahasa Malaysia, maksimum 150 patah perkataan:
1. Trend minggu ini berbanding minggu sebelum (guna nombor yang diberi).
2. Satu perkara yang paling penting untuk diberi perhatian minggu depan.
3. Satu hipotesis untuk diuji minggu depan (angle atau audience mana).
Jangan bodek. Kalau minggu ini teruk, cakap teruk."""


def build_weekly_payload(as_of: date) -> dict:
    """Two 7-day blocks, this week vs last week, all pre-computed."""
    history = db.fetch_metric_history("ad", as_of - timedelta(days=13), as_of)
    this_week = [r for r in history if r.date > as_of - timedelta(days=7)]
    last_week = [r for r in history if r.date <= as_of - timedelta(days=7)]

    q_this = db.count_qualified_since(as_of - timedelta(days=6))
    t_this = aggregate(this_week, qualified_leads=q_this)
    t_last = aggregate(last_week)

    names = db.fetch_ad_names()
    cfg = get_thresholds()
    min_spend = cfg["rules"]["cpl_spike"]["min_spend_rm"]
    best = rank_ads(this_week, "cpl", lowest_is_best=True, min_spend=min_spend)

    return {
        "tarikh_akhir": as_of.isoformat(),
        "minggu_ini": {
            "spend_rm": t_this.spend,
            "leads": t_this.leads,
            "qualified": t_this.qualified_leads,
            "cpl_rm": t_this.cpl,
            "cpql_rm": t_this.cpql,
            "ctr_pct": t_this.ctr,
        },
        "minggu_lepas": {
            "spend_rm": t_last.spend,
            "leads": t_last.leads,
            "cpl_rm": t_last.cpl,
            "ctr_pct": t_last.ctr,
        },
        "ads_terbaik_minggu_ini": [
            {
                "nama": names.get(r.ref_id, r.ref_id),
                "spend_rm": round(r.spend, 2),
                "leads": r.leads,
                "cpl_rm": r.cpl,
            }
            for r in best[:3]
        ],
    }


def run_weekly(as_of: date | None = None, to: str = notify.Recipient.BOTH) -> str:
    import json

    from ..llm import MID, complete

    as_of = as_of or (today_myt() - timedelta(days=1))
    with db.agent_run("reporter_weekly") as run:
        payload = build_weekly_payload(as_of)
        t, l = payload["minggu_ini"], payload["minggu_lepas"]

        summary = complete(
            WEEKLY_SYSTEM,
            json.dumps(payload, ensure_ascii=False, indent=2),
            tier=MID,
            max_tokens=700,
        )

        message = "\n".join(
            [
                f"*RINGKASAN MINGGUAN* — sehingga {as_of.strftime('%d %b %Y')}",
                "",
                "*Minggu ini*",
                f"• Spend: {rm(t['spend_rm'])}",
                f"• Lead: {num(t['leads'])}  ·  Qualified: {num(t['qualified'])}",
                f"• CPL: {rm(t['cpl_rm'])}  ·  CPQL: {rm(t['cpql_rm'])}",
                f"• CTR: {pct(t['ctr_pct'])}",
                "",
                "*Minggu lepas*",
                f"• Spend: {rm(l['spend_rm'])}  ·  Lead: {num(l['leads'])}  "
                f"·  CPL: {rm(l['cpl_rm'])}",
                "",
                "*Analisis*",
                summary.strip(),
            ]
        )
        notify.send(message, to=to)
        run["summary"] = f"weekly to {as_of}"
    return message
