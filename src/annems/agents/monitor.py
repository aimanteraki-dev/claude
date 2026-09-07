"""AGENT 3 — Monitoring / Alert. Rules in code, cheap LLM only for wording.

Ref: CLAUDE.md Agent 3 spec. Runs every 3 hours during ad-serving hours.

Design rule: every threshold decision happens in `evaluate_rules`, a pure
function with no DB, no network and no LLM — so the tests can simulate breaches
directly. The LLM never decides whether to alert; it only phrases one.

Alert format is enforced structurally: numbers + diagnosis + recommendation.
"Prestasi menurun" with no figures is impossible to emit from this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from .. import db, notify
from ..config import get_thresholds, now_myt
from ..llm import CHEAP, complete
from ..metrics import MetricRow, compute_baseline

log = logging.getLogger(__name__)

SEVERITY_ICON = {"info": "ℹ️", "warn": "⚠️", "critical": "🚨"}


@dataclass
class Alert:
    rule: str
    severity: str
    ref_id: str
    ref_name: str
    facts: dict = field(default_factory=dict)
    diagnosis: str = ""
    recommendation: str = ""

    def to_text(self) -> str:
        """Deterministic message. Used as-is if the LLM rewrite fails."""
        icon = SEVERITY_ICON.get(self.severity, "⚠️")
        fact_lines = "\n".join(f"• {k}: {v}" for k, v in self.facts.items())
        return (
            f"{icon} *{self.rule.replace('_', ' ').upper()}*\n"
            f"Ad: {self.ref_name}\n"
            f"{fact_lines}\n\n"
            f"Diagnosis: {self.diagnosis}\n"
            f"Cadangan: {self.recommendation}"
        )


# ---------------------------------------------------------------------------
# Pure rule evaluation — the testable core
# ---------------------------------------------------------------------------


def evaluate_rules(
    today_rows: list[MetricRow],
    history: list[MetricRow],
    cfg: dict,
    names: dict[str, str] | None = None,
    as_of: date | None = None,
) -> list[Alert]:
    """Apply every enabled alert rule. No side effects, no I/O.

    `today_rows` are the rows being judged; `history` supplies the baselines
    (it may include today's rows — compute_baseline only looks strictly before).
    """
    names = names or {}
    rules = cfg["rules"]
    dq = cfg["data_quality"]
    alerts: list[Alert] = []

    for row in today_rows:
        name = names.get(row.ref_id, row.ref_id)
        as_of_date = as_of or row.date

        # --- Rule 1: burning money with nothing to show for it ---------------
        r = rules["spend_no_leads"]
        if r["enabled"] and row.spend > r["min_spend_rm"] and row.leads == 0:
            alerts.append(
                Alert(
                    rule="spend_no_leads",
                    severity=r["severity"],
                    ref_id=row.ref_id,
                    ref_name=name,
                    facts={
                        "Spend hari ini": f"RM{row.spend:,.2f}",
                        "Lead": "0",
                        "Klik": f"{row.clicks:,}",
                        "CTR": _pct(row.ctr),
                    },
                    diagnosis=(
                        "Klik ada tapi lead sifar — kemungkinan besar masalah landing "
                        "page atau tracking, bukan iklan."
                        if row.clicks >= 20
                        else "Klik pun sangat sedikit — masalah pada creative atau audience."
                    ),
                    recommendation=(
                        "Test borang Sesi Diagnosis sendiri sekarang. Kalau borang OK, "
                        "pause ad ini dan semak tracking sebelum sambung spend."
                    ),
                )
            )

        # --- Rule 2: CPL spike vs its own 7-day baseline ----------------------
        r = rules["cpl_spike"]
        if r["enabled"] and row.spend >= r["min_spend_rm"] and row.cpl is not None:
            b = compute_baseline(history, "cpl", as_of_date, row.level, row.ref_id)
            if (
                b.avg_7d
                and b.days_of_data >= dq["min_days_for_baseline"]
                and row.cpl > b.avg_7d * r["multiple_of_baseline"]
            ):
                alerts.append(
                    Alert(
                        rule="cpl_spike",
                        severity=r["severity"],
                        ref_id=row.ref_id,
                        ref_name=name,
                        facts={
                            "CPL hari ini": f"RM{row.cpl:,.2f}",
                            "Baseline 7 hari": f"RM{b.avg_7d:,.2f}",
                            "Perubahan": _delta(b.delta_pct),
                            "Spend": f"RM{row.spend:,.2f}",
                        },
                        diagnosis=(
                            f"CPL naik melebihi {r['multiple_of_baseline']}× baseline sendiri. "
                            "Kos setiap lead makin mahal untuk ad yang sama."
                        ),
                        recommendation=(
                            "Semak CTR dan frequency ad ini dalam laporan pagi. CTR jatuh "
                            "= tukar creative. Frequency tinggi = tukar audience."
                        ),
                    )
                )

        # --- Rule 3: CTR collapse = creative fatigue --------------------------
        r = rules["ctr_drop"]
        if r["enabled"] and row.impressions >= r["min_impressions"] and row.ctr is not None:
            b = compute_baseline(history, "ctr", as_of_date, row.level, row.ref_id)
            if (
                b.avg_7d
                and b.days_of_data >= dq["min_days_for_baseline"]
                and b.delta_pct is not None
                and b.delta_pct <= -r["drop_pct"]
            ):
                alerts.append(
                    Alert(
                        rule="ctr_drop",
                        severity=r["severity"],
                        ref_id=row.ref_id,
                        ref_name=name,
                        facts={
                            "CTR hari ini": _pct(row.ctr),
                            "Baseline 7 hari": _pct(b.avg_7d),
                            "Perubahan": _delta(b.delta_pct),
                            "Frequency": f"{row.frequency:.2f}",
                        },
                        diagnosis=(
                            "CTR jatuh mendadak berbanding baseline sendiri — corak "
                            "creative fatigue. Audience dah biasa tengok creative ini."
                        ),
                        recommendation=(
                            "Minta creative baru (/creative) guna angle berbeza. Kekalkan "
                            "audience, tukar hook."
                        ),
                    )
                )

        # --- Rule 4: frequency = audience saturation --------------------------
        r = rules["frequency_high"]
        if (
            r["enabled"]
            and row.impressions >= r["min_impressions"]
            and row.frequency >= r["max_frequency"]
        ):
            alerts.append(
                Alert(
                    rule="frequency_high",
                    severity=r["severity"],
                    ref_id=row.ref_id,
                    ref_name=name,
                    facts={
                        "Frequency": f"{row.frequency:.2f}",
                        "Had": f"{r['max_frequency']:.2f}",
                        "Reach": f"{row.reach:,}",
                        "CPM": _rm(row.cpm),
                    },
                    diagnosis=(
                        "Orang yang sama tengok iklan ini terlalu kerap — audience "
                        "saturation. Kos akan naik walaupun creative masih elok."
                    ),
                    recommendation=(
                        "Luaskan audience atau naikkan exclusion. Tukar creative sahaja "
                        "takkan selesaikan ini."
                    ),
                )
            )

    return alerts


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:.2f}%"


def _rm(v: float | None) -> str:
    return "—" if v is None else f"RM{v:,.2f}"


def _delta(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{'+' if v > 0 else ''}{v:.1f}%"


# ---------------------------------------------------------------------------
# Wording (cheap LLM) — optional polish over an already-complete message
# ---------------------------------------------------------------------------

WORDING_SYSTEM = """Kau tulis mesej alert ringkas untuk Aiman dalam Bahasa Malaysia.

Input adalah alert yang sudah lengkap dengan nombor, diagnosis dan cadangan.
Tugas kau HANYA kemaskan ayat supaya senang baca atas telefon.

PERATURAN:
- KEKALKAN setiap nombor persis seperti diberi. Jangan tukar, bulatkan, atau tambah.
- Jangan buang bahagian nombor, diagnosis, atau cadangan.
- Jangan tambah nombor atau fakta baru.
- Maksimum 80 patah perkataan. Tiada bebelan.
Balas dengan mesej sahaja."""


def polish(alert: Alert) -> str:
    """Rewrite for readability. Falls back to the deterministic text on error."""
    base = alert.to_text()
    try:
        return complete(WORDING_SYSTEM, base, tier=CHEAP, max_tokens=300) or base
    except Exception:
        log.exception("Alert wording failed for %s; sending raw text", alert.rule)
        return base


# ---------------------------------------------------------------------------
# The scheduled run
# ---------------------------------------------------------------------------


def within_active_hours(when: datetime, cfg: dict) -> bool:
    m = cfg["monitoring"]
    return m["active_hours_start"] <= when.hour < m["active_hours_end"]


def run(as_of: date | None = None, force: bool = False) -> list[Alert]:
    """Evaluate today's data and send any alerts that pass the cooldown."""
    cfg = get_thresholds()
    now = now_myt()
    if not force and not within_active_hours(now, cfg):
        log.info("Outside ad-serving hours (%s) — skipping monitor run", now.hour)
        return []

    as_of = as_of or now.date()
    with db.agent_run("agent_3_monitor") as run_rec:
        history = db.fetch_window("ad", as_of, days=14)
        today_rows = [r for r in history if r.date == as_of]
        names = db.fetch_ad_names()

        alerts = evaluate_rules(today_rows, history, cfg, names, as_of)
        cooldown = cfg["monitoring"]["cooldown_hours"]

        sent = 0
        for alert in alerts:
            if db.recent_alert_exists(alert.rule, alert.ref_id, cooldown):
                log.info("Cooldown active for %s/%s", alert.rule, alert.ref_id)
                continue
            text = polish(alert)
            notify.send(text, to=notify.Recipient.AIMAN)
            db.record_alert(alert.rule, alert.severity, text, alert.ref_id)
            sent += 1

        run_rec["summary"] = f"{len(alerts)} alerts raised, {sent} sent"
        log.info("monitor: %d raised, %d sent", len(alerts), sent)
    return alerts
