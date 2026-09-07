"""AGENT 4 — Penulis Iklan (LLM mid tier + image API).

Ref: CLAUDE.md Agent 4 spec.

Triggered manually by Aiman (Telegram /creative) or suggested by Agent 2 when
fatigue is detected. Never publishes anything — output is a draft plus an
approval record. Publishing stays manual in Ads Manager (section 6).

Tagging is mandatory: concept / angle / format / awareness_level are written on
every creative at creation time. That metadata is what makes Phase 2's Learning
Memory possible, so a creative without tags is rejected before it is stored.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import yaml

from .. import db
from ..config import REPO_ROOT
from ..llm import MID, complete_json, generate_image
from ..metrics import rank_ads

log = logging.getLogger(__name__)

BRAND_PATH = REPO_ROOT / "config" / "brand.yaml"


@lru_cache(maxsize=1)
def brand() -> dict:
    with BRAND_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class Creative:
    """One complete ad option. Tags are not optional."""

    concept: str
    angle: str
    format: str
    awareness_level: str
    hook: str
    primary_text: str
    headline: str
    cta: str
    image_prompt: str = ""
    image_bytes: bytes | None = field(default=None, repr=False)
    image_url: str | None = None
    qa_score: float | None = None
    qa_status: str | None = None
    qa_notes: str = ""

    def validate_tags(self) -> None:
        b = brand()
        missing = [
            f for f in ("concept", "angle", "format", "awareness_level", "hook",
                        "primary_text", "headline", "cta")
            if not str(getattr(self, f, "")).strip()
        ]
        if missing:
            raise ValueError(f"Creative missing mandatory fields: {', '.join(missing)}")
        if self.concept not in b["concepts"]:
            raise ValueError(
                f"Unknown concept {self.concept!r}. Use one of: {list(b['concepts'])}. "
                "Consistent naming is what makes the Tagging Log usable."
            )
        if self.awareness_level not in b["awareness_levels"]:
            raise ValueError(f"Unknown awareness level {self.awareness_level!r}")
        if self.format not in b["formats"]:
            raise ValueError(f"Unknown format {self.format!r}")

    def to_db(self, created_by: str = "agent_4") -> dict:
        return {
            "concept": self.concept,
            "angle": self.angle,
            "format": self.format,
            "awareness_level": self.awareness_level,
            "hook": self.hook,
            "primary_text": self.primary_text,
            "headline": self.headline,
            "cta": self.cta,
            "image_url": self.image_url,
            "qa_score": self.qa_score,
            "qa_status": self.qa_status,
            "created_by": created_by,
        }

    def to_telegram(self) -> str:
        return "\n".join(
            [
                f"*{self.concept}* — _{self.angle}_",
                f"`{self.format}` · `{self.awareness_level}`",
                "",
                f"*Hook:* {self.hook}",
                "",
                self.primary_text,
                "",
                f"*Headline:* {self.headline}",
                f"*CTA:* {self.cta}",
                "",
                f"QA: {self.qa_status} ({self.qa_score})" if self.qa_status else "",
            ]
        ).strip()


# ---------------------------------------------------------------------------
# Performance context — what has actually been working
# ---------------------------------------------------------------------------


def angle_performance(as_of: date, lookback_days: int = 30) -> dict:
    """Which concepts/angles won and lost recently, joined via creatives.

    Pure lookup + the metric engine's ranking. If tagging discipline has
    slipped, this returns little — and the prompt says so honestly rather than
    inventing a winning angle.
    """
    start = as_of - timedelta(days=lookback_days)
    rows = db.fetch_metric_history("ad", start, as_of)
    names = db.fetch_ad_names()

    try:
        res = db.get_client().table("creatives").select(
            "concept,angle,format,awareness_level,meta_ad_name"
        ).execute()
        tagged = res.data or []
    except Exception:
        log.exception("Could not read creatives table for angle performance")
        tagged = []

    # Aggregate spend/leads per ad, then attribute to a concept/angle by name.
    per_ad: dict[str, dict[str, Any]] = {}
    for r in rows:
        slot = per_ad.setdefault(r.ref_id, {"spend": 0.0, "leads": 0, "clicks": 0,
                                            "impressions": 0})
        slot["spend"] += r.spend
        slot["leads"] += r.leads
        slot["clicks"] += r.clicks
        slot["impressions"] += r.impressions

    by_name = {t.get("meta_ad_name"): t for t in tagged if t.get("meta_ad_name")}
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for ad_id, stats in per_ad.items():
        tag = by_name.get(names.get(ad_id, ""))
        if not tag:
            continue
        key = (tag["concept"], tag["angle"])
        slot = buckets.setdefault(key, {"spend": 0.0, "leads": 0})
        slot["spend"] += stats["spend"]
        slot["leads"] += stats["leads"]

    summary = []
    for (concept, angle), s in buckets.items():
        cpl = round(s["spend"] / s["leads"], 2) if s["leads"] else None
        summary.append(
            {"concept": concept, "angle": angle, "spend_rm": round(s["spend"], 2),
             "leads": s["leads"], "cpl_rm": cpl}
        )
    summary.sort(key=lambda x: (x["cpl_rm"] is None, x["cpl_rm"] or 0))

    best_ads = rank_ads(rows, "cpl", lowest_is_best=True, min_spend=50.0)
    return {
        "tempoh_hari": lookback_days,
        "angle_berprestasi": summary[:8],
        "nota": (
            "Tiada creative bertag dalam tempoh ini — tulis creative baru tanpa "
            "data pemenang lepas, dan JANGAN dakwa apa-apa angle terbukti menang."
            if not summary
            else ""
        ),
        "ad_cpl_terendah": [
            {"nama": names.get(r.ref_id, r.ref_id), "cpl_rm": r.cpl, "spend_rm": round(r.spend, 2)}
            for r in best_ads[:3]
        ],
    }


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Kau copywriter kanan untuk Annems Leadership Solution Sdn Bhd.

Kau tulis iklan Meta dalam Bahasa Malaysia untuk founder syarikat SME Malaysia
berpendapatan RM2 juta+ setahun. Mereka bukan pemula. Mereka sibuk, skeptikal,
dan dah pernah nampak banyak iklan kursus. Tulis macam orang yang faham bisnes
mereka, bukan macam penjual.

PERATURAN:
- Nada premium corporate: tenang, berwibawa. Bukan hype, bukan motivasi murahan.
- JANGAN janji hasil, pendapatan, atau jaminan.
- JANGAN guna nombor prestasi, statistik, atau testimoni yang tak diberi dalam
  input. Kalau tiada data, jangan reka.
- Setiap creative WAJIB guna concept dan angle dari senarai yang diberi. Jangan
  cipta nama concept baru — konsistensi nama itu yang buat data berguna nanti.
- Primary text: 60-120 patah perkataan. Hook: satu ayat, di bawah 15 patah.
- Headline: bawah 40 aksara.
- image_prompt: dalam Bahasa Inggeris, untuk model gambar. Gaya editorial korporat
  premium, palet navy dan gold. JANGAN minta teks dalam gambar (model gambar tak
  reliable untuk teks BM). Fokus pada suasana dan subjek.

Balas JSON sahaja dengan struktur ini:
{"creatives": [{"concept": "...", "angle": "...", "format": "...",
  "awareness_level": "...", "hook": "...", "primary_text": "...",
  "headline": "...", "cta": "...", "image_prompt": "..."}]}"""


def build_brief(as_of: date, n: int, concept: str | None = None) -> str:
    b = brand()
    perf = angle_performance(as_of)
    payload = {
        "arahan": f"Hasilkan {n} pilihan creative yang BERBEZA angle antara satu sama lain.",
        "concept_dikehendaki": concept or "bebas pilih dari senarai",
        "brand": b["brand"],
        "syarikat": b["company"],
        "tawaran": b["offer"],
        "audience": b["audience"],
        "senarai_concept_dan_angle": b["concepts"],
        "format_dibenarkan": b["formats"],
        "awareness_dibenarkan": b["awareness_levels"],
        "elak": b["brand"]["avoid"],
        "prestasi_lepas": perf,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def generate(as_of: date, n: int = 3, concept: str | None = None) -> list[Creative]:
    """Produce n tagged creative drafts. Images are generated separately."""
    brief = build_brief(as_of, n, concept)
    data = complete_json(SYSTEM_PROMPT, brief, tier=MID, max_tokens=2500)

    creatives: list[Creative] = []
    for item in data.get("creatives", [])[:n]:
        c = Creative(
            concept=str(item.get("concept", "")).strip(),
            angle=str(item.get("angle", "")).strip(),
            format=str(item.get("format", "Static 4:5")).strip(),
            awareness_level=str(item.get("awareness_level", "Problem Aware")).strip(),
            hook=str(item.get("hook", "")).strip(),
            primary_text=str(item.get("primary_text", "")).strip(),
            headline=str(item.get("headline", "")).strip(),
            cta=str(item.get("cta", brand()["offer"]["cta_default"])).strip(),
            image_prompt=str(item.get("image_prompt", "")).strip(),
        )
        try:
            c.validate_tags()
        except ValueError as exc:
            log.warning("Dropping creative with bad tags: %s", exc)
            continue
        creatives.append(c)

    if not creatives:
        raise RuntimeError("Agent 4 produced no validly tagged creatives")
    return creatives


REVISE_SYSTEM = """Kau copywriter kanan Annems. Satu creative kau gagal QA.

Kau diberi creative asal dan senarai masalah dari QA. Betulkan masalah tersebut.
KEKALKAN concept, angle, format dan awareness_level yang sama — ini pembetulan,
bukan idea baru. Kalau masalah pada gambar, tulis image_prompt yang lebih baik.

Peraturan asal masih terpakai: Bahasa Malaysia, nada premium corporate, tiada
janji hasil, tiada nombor yang direka.

Balas JSON sahaja:
{"concept": "...", "angle": "...", "format": "...", "awareness_level": "...",
 "hook": "...", "primary_text": "...", "headline": "...", "cta": "...",
 "image_prompt": "..."}"""


def revise(creative: Creative, qa_feedback: str) -> Creative:
    """One corrective pass after a QA failure. Tags are carried over unchanged."""
    payload = json.dumps(
        {
            "creative_asal": creative_to_dict(creative),
            "maklum_balas_qa": json.loads(qa_feedback) if qa_feedback.strip().startswith("{") else qa_feedback,
            "panduan_brand": brand()["brand"],
        },
        ensure_ascii=False,
        indent=2,
    )
    item = complete_json(REVISE_SYSTEM, payload, tier=MID, max_tokens=1500)
    revised = Creative(
        concept=creative.concept,          # tags are fixed across a revision
        angle=creative.angle,
        format=creative.format,
        awareness_level=creative.awareness_level,
        hook=str(item.get("hook") or creative.hook).strip(),
        primary_text=str(item.get("primary_text") or creative.primary_text).strip(),
        headline=str(item.get("headline") or creative.headline).strip(),
        cta=str(item.get("cta") or creative.cta).strip(),
        image_prompt=str(item.get("image_prompt") or creative.image_prompt).strip(),
    )
    revised.validate_tags()
    return revised


IMAGE_STYLE_SUFFIX = (
    " Premium corporate editorial photography, deep navy and muted gold palette, "
    "soft directional light, Malaysian business setting, restrained and serious "
    "mood, no text, no logos, no watermarks, photorealistic, 4:5 vertical."
)


def render_image(creative: Creative) -> bytes:
    """Generate the 4:5 image for a creative."""
    prompt = (creative.image_prompt or creative.hook) + IMAGE_STYLE_SUFFIX
    return generate_image(prompt, size="1024x1536")


def creative_to_dict(c: Creative) -> dict:
    d = asdict(c)
    d.pop("image_bytes", None)
    return d
