"""AGENT 2 — Performance Analyst (LLM, mid tier).

Ref: CLAUDE.md Agent 2 spec.

The division of labour is strict:
  * This module's Python computes every number and every comparison, and
    derives mechanical "signals" (fatigue-shaped, saturation-shaped, ...).
  * The LLM receives that as JSON and only writes the explanation in Bahasa
    Malaysia. It is told, in the system prompt, that it may not compute or
    invent a single figure.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .. import db
from ..config import get_thresholds
from ..llm import MID, complete
from ..metrics import (
    Baseline,
    MetricRow,
    Totals,
    aggregate,
    compute_baseline,
    rank_ads,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Kau Performance Analyst untuk Annems Leadership Solution.

PERATURAN MUTLAK:
1. SEMUA nombor sudah dikira untuk kau dalam JSON input. Kau DILARANG mengira,
   menjumlah, membahagi, atau menganggar apa-apa nombor sendiri.
2. Kau hanya boleh sebut nombor yang WUJUD dalam JSON input. Kalau satu nombor
   tiada (null), kau kata "tak dapat diukur" — jangan reka, jangan anggar.
3. Kalau data tak cukup (flag `data_cukup` false), kata terus data belum cukup
   untuk buat kesimpulan. Jangan paksa diagnosis.
4. Jangan puji atau bodek. Kalau prestasi teruk, cakap teruk.

TUGAS: Diagnosis dalam Bahasa Malaysia profesional, tiga bahagian:

APA JADI — fakta ringkas dengan nombor dari JSON.
KENAPA — bezakan punca sebenar antara empat kemungkinan ini:
   * Creative fatigue: CTR jatuh, frequency naik, CPM stabil, audience sama.
   * Audience saturation: reach mendatar, frequency tinggi, CPM naik.
   * Landing page / offer: CTR sihat tapi CVR (klik->lead) jatuh.
   * Tracking issue: klik ada, lead sifar mengejut, atau nombor mustahil.
   Sebut yang mana satu, dan bukti nombor mana yang tunjuk begitu. Kalau tak
   dapat bezakan dengan data yang ada, kata begitu.
TINDAKAN HARI INI — maksimum 3 tindakan konkrit, spesifik pada ad/adset yang
   dinamakan dalam data. Bukan nasihat umum.

Panjang: bawah 200 patah perkataan. Tulis untuk Aiman baca atas telefon."""


@dataclass
class AdSnapshot:
    """One ad's numbers plus its own baselines — everything pre-computed."""

    ref_id: str
    name: str
    spend: float
    impressions: int
    clicks: int
    leads: int
    cpl: float | None
    ctr: float | None
    cpm: float | None
    cvr: float | None
    frequency: float
    ctr_vs_7d_pct: float | None = None
    cpl_vs_7d_pct: float | None = None
    cpm_vs_7d_pct: float | None = None
    days_of_data: int = 0
    signals: list[str] = field(default_factory=list)


@dataclass
class DataPack:
    """The complete, pre-computed input an LLM is allowed to interpret."""

    tarikh: str
    semalam: dict
    tiga_hari: dict
    tujuh_hari: dict
    empat_belas_hari: dict
    cpql_7d: float | None
    qualified_leads_7d: int
    ads: list[dict]
    ads_terbaik: list[dict]
    ads_terlemah: list[dict]
    data_cukup: bool
    nota_kualiti_data: list[str]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, default=str)


# ---------------------------------------------------------------------------
# Signal detection — mechanical, in code, so the LLM only has to name the cause
# ---------------------------------------------------------------------------


def detect_signals(snap: AdSnapshot, cfg: dict) -> list[str]:
    """Rule-based hints. These describe shapes in the data, not conclusions."""
    rules = cfg["rules"]
    dq = cfg["data_quality"]
    out: list[str] = []

    if snap.impressions < dq["min_impressions_for_ctr"]:
        out.append("impressions_terlalu_rendah_untuk_ctr")
        return out

    if snap.ctr_vs_7d_pct is not None and snap.ctr_vs_7d_pct <= -rules["ctr_drop"]["drop_pct"]:
        out.append("ctr_jatuh_ketara")
    if snap.frequency >= rules["frequency_high"]["max_frequency"]:
        out.append("frequency_tinggi")
    if snap.cpm_vs_7d_pct is not None and snap.cpm_vs_7d_pct >= 20:
        out.append("cpm_naik")
    if snap.cpl_vs_7d_pct is not None and snap.cpl_vs_7d_pct >= 50:
        out.append("cpl_melonjak")
    if snap.clicks >= 20 and snap.leads == 0:
        out.append("klik_ada_lead_sifar")
    if snap.spend >= rules["spend_no_leads"]["min_spend_rm"] and snap.leads == 0:
        out.append("spend_tinggi_tanpa_lead")

    # Composite shapes — the four causes the analyst must distinguish between.
    if "ctr_jatuh_ketara" in out and "frequency_tinggi" in out and "cpm_naik" not in out:
        out.append("corak_creative_fatigue")
    if "frequency_tinggi" in out and "cpm_naik" in out:
        out.append("corak_audience_saturation")
    if snap.ctr is not None and snap.ctr_vs_7d_pct is not None and snap.ctr_vs_7d_pct > -10:
        if snap.cvr is not None and snap.cvr < 1.0 and snap.clicks >= 30:
            out.append("corak_masalah_landing_page")
    if "klik_ada_lead_sifar" in out and snap.clicks >= 50:
        out.append("corak_kemungkinan_tracking_rosak")
    return out


# ---------------------------------------------------------------------------
# Assembling the data pack
# ---------------------------------------------------------------------------


def _totals_dict(t: Totals) -> dict:
    return {
        "spend_rm": t.spend,
        "impressions": t.impressions,
        "clicks": t.clicks,
        "leads": t.leads,
        "cpl_rm": t.cpl,
        "ctr_pct": t.ctr,
        "cpm_rm": t.cpm,
        "cpc_rm": t.cpc,
        "cvr_pct": t.cvr,
        "cpql_rm": t.cpql,
        "qualified_leads": t.qualified_leads,
        "hari": t.days,
    }


def _window(history: list[MetricRow], as_of: date, days: int) -> list[MetricRow]:
    start = as_of - timedelta(days=days - 1)
    return [r for r in history if start <= r.date <= as_of]


def build_data_pack(as_of: date, level: str = "ad") -> DataPack:
    """Pull history, compute everything, and package it for the model."""
    cfg = get_thresholds()
    history = db.fetch_window(level, as_of, days=14)
    names = db.fetch_ad_names() if level == "ad" else {}

    yesterday_rows = _window(history, as_of, 1)
    qualified_7d = db.count_qualified_since(as_of - timedelta(days=6))

    t_1 = aggregate(_window(history, as_of, 1))
    t_3 = aggregate(_window(history, as_of, 3))
    t_7 = aggregate(_window(history, as_of, 7), qualified_leads=qualified_7d)
    t_14 = aggregate(_window(history, as_of, 14))

    snapshots: list[AdSnapshot] = []
    for row in yesterday_rows:
        ctr_b = compute_baseline(history, "ctr", as_of, level, row.ref_id)
        cpl_b = compute_baseline(history, "cpl", as_of, level, row.ref_id)
        cpm_b = compute_baseline(history, "cpm", as_of, level, row.ref_id)
        snap = AdSnapshot(
            ref_id=row.ref_id,
            name=names.get(row.ref_id, row.ref_id),
            spend=row.spend,
            impressions=row.impressions,
            clicks=row.clicks,
            leads=row.leads,
            cpl=row.cpl,
            ctr=row.ctr,
            cpm=row.cpm,
            cvr=row.cvr,
            frequency=row.frequency,
            ctr_vs_7d_pct=ctr_b.delta_pct,
            cpl_vs_7d_pct=cpl_b.delta_pct,
            cpm_vs_7d_pct=cpm_b.delta_pct,
            days_of_data=ctr_b.days_of_data,
        )
        snap.signals = detect_signals(snap, cfg)
        snapshots.append(snap)

    min_spend = cfg["rules"]["cpl_spike"]["min_spend_rm"]
    best = rank_ads(yesterday_rows, "cpl", lowest_is_best=True, min_spend=min_spend)
    worst = list(reversed(best))
    top_n = cfg["reporting"]["top_n_ads"]

    notes: list[str] = []
    max_days = max((s.days_of_data for s in snapshots), default=0)
    if max_days < cfg["data_quality"]["min_days_for_baseline"]:
        notes.append(
            f"Baseline baru {max_days} hari data — belum cukup untuk banding trend."
        )
    if t_7.leads < cfg["data_quality"]["min_leads_for_cpl"]:
        notes.append(f"Hanya {t_7.leads} lead dalam 7 hari — CPL belum stabil.")
    if not yesterday_rows:
        notes.append("Tiada data langsung untuk tarikh ini.")
    if qualified_7d == 0 and t_7.leads > 0:
        notes.append(
            "Tiada lead bertanda 'qualified' dalam GHL — CPQL tak dapat dikira. "
            "Cek disiplin pipeline GHL."
        )

    return DataPack(
        tarikh=as_of.isoformat(),
        semalam=_totals_dict(t_1),
        tiga_hari=_totals_dict(t_3),
        tujuh_hari=_totals_dict(t_7),
        empat_belas_hari=_totals_dict(t_14),
        cpql_7d=t_7.cpql,
        qualified_leads_7d=qualified_7d,
        ads=[asdict(s) for s in snapshots],
        ads_terbaik=[_ad_brief(r, names) for r in best[:top_n]],
        ads_terlemah=[_ad_brief(r, names) for r in worst[:top_n]],
        data_cukup=bool(yesterday_rows) and not notes,
        nota_kualiti_data=notes,
    )


def _ad_brief(row: MetricRow, names: dict[str, str]) -> dict:
    return {
        "nama": names.get(row.ref_id, row.ref_id),
        "ref_id": row.ref_id,
        "spend_rm": round(row.spend, 2),
        "leads": row.leads,
        "cpl_rm": row.cpl,
        "ctr_pct": row.ctr,
    }


# ---------------------------------------------------------------------------
# The agent itself
# ---------------------------------------------------------------------------


def analyse(as_of: date, level: str = "ad") -> tuple[str, DataPack]:
    """Return (diagnosis in Bahasa Malaysia, the data pack it was based on)."""
    pack = build_data_pack(as_of, level)

    if not pack.ads and not pack.semalam["spend_rm"]:
        return (
            "Tiada data iklan untuk tarikh ini. Sama ada tiada ad aktif, atau "
            "data pull gagal — cek log Agent 1 sebelum buat apa-apa keputusan.",
            pack,
        )

    user_prompt = (
        "Berikut data prestasi iklan yang SUDAH DIKIRA. Buat diagnosis.\n\n"
        f"{pack.to_json()}"
    )
    diagnosis = complete(SYSTEM_PROMPT, user_prompt, tier=MID, max_tokens=900)
    return diagnosis, pack


def persist_baselines(as_of: date, level: str = "ad") -> int:
    """Store computed baselines so trends survive beyond the 14-day window."""
    from ..metrics import compute_all_baselines

    history = db.fetch_window(level, as_of, days=14)
    if not history:
        return 0
    baselines: list[Baseline] = compute_all_baselines(history, as_of)
    return db.upsert_baselines([b.to_db() for b in baselines])
