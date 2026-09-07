"""AGENT 5 — Creative QA (LLM with vision, cheap/mid tier).

Ref: CLAUDE.md Agent 5 spec.

Runs automatically on every generated creative before it reaches Aiman. Scores
six dimensions, returns PASS / FAIL. A FAIL triggers exactly one regeneration
with the QA feedback attached; if it fails again the creative still reaches
Aiman, but flagged, so nothing disappears silently.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from ..llm import MID, as_data_uri, complete_json
from .ad_writer import Creative, brand

log = logging.getLogger(__name__)

DIMENSIONS = (
    "ejaan_bahasa",        # typos, grammar, unnatural Bahasa Malaysia
    "patuh_brand",         # tone, colors, premium corporate feel
    "artifak_ai",          # warped hands/faces, nonsense text, uncanny artifacts
    "kejelasan_mesej",     # is the message obvious in 2 seconds
    "kebolehbacaan_mobile",# readable on a phone screen
    "risiko_polisi_iklan", # Meta ad policy risk (claims, personal attributes)
)

PASS_MARK = 7.0          # every dimension must reach this
CRITICAL_DIMENSIONS = ("risiko_polisi_iklan", "artifak_ai")
CRITICAL_PASS_MARK = 8.0  # these two are held to a higher bar

SYSTEM_PROMPT = """Kau Creative QA untuk Annems Leadership Solution. Kau penapis
terakhir sebelum creative sampai ke Aiman. Kerja kau cari masalah, bukan puji.

Nilai creative (teks + gambar) pada enam dimensi, skor 0-10 setiap satu:
- ejaan_bahasa: ejaan, tatabahasa, Bahasa Malaysia yang berbunyi natural.
- patuh_brand: nada premium corporate, palet navy/gold, bukan hype.
- artifak_ai: tangan/muka pelik, teks karut dalam gambar, rupa palsu. 10 = bersih.
- kejelasan_mesej: dalam 2 saat, jelas ke apa iklan ini pasal?
- kebolehbacaan_mobile: elemen cukup besar dan jelas atas skrin telefon.
- risiko_polisi_iklan: janji hasil, dakwaan kewangan, sasaran ciri peribadi.
  10 = tiada risiko langsung.

Untuk SETIAP dimensi bawah 8, tulis masalah spesifik dan cara betulkan.
Jangan longgar. Kalau ragu, beri skor rendah.

Balas JSON sahaja:
{"skor": {"ejaan_bahasa": 0-10, "patuh_brand": 0-10, "artifak_ai": 0-10,
  "kejelasan_mesej": 0-10, "kebolehbacaan_mobile": 0-10,
  "risiko_polisi_iklan": 0-10},
 "masalah": ["..."], "cara_betulkan": ["..."], "ringkasan": "satu ayat"}"""


@dataclass
class QAResult:
    scores: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    summary: str = ""
    status: str = "FAIL"  # PASS | FAIL | FLAGGED
    error: str | None = None

    @property
    def average(self) -> float:
        return round(sum(self.scores.values()) / len(self.scores), 2) if self.scores else 0.0

    @property
    def failing(self) -> list[str]:
        """Dimensions that did not clear their bar."""
        out = []
        for dim, score in self.scores.items():
            bar = CRITICAL_PASS_MARK if dim in CRITICAL_DIMENSIONS else PASS_MARK
            if score < bar:
                out.append(f"{dim} ({score})")
        return out

    def feedback_for_regeneration(self) -> str:
        return json.dumps(
            {
                "dimensi_gagal": self.failing,
                "masalah": self.issues,
                "cara_betulkan": self.fixes,
            },
            ensure_ascii=False,
            indent=2,
        )

    def to_telegram(self) -> str:
        icon = {"PASS": "✅", "FAIL": "❌", "FLAGGED": "⚠️"}.get(self.status, "•")
        lines = [f"{icon} QA {self.status} — purata {self.average}/10"]
        if self.failing:
            lines.append("Gagal: " + ", ".join(self.failing))
        if self.summary:
            lines.append(self.summary)
        return "\n".join(lines)


def review(creative: Creative, image_bytes: bytes | None = None) -> QAResult:
    """Score one creative. Never raises — a broken QA must not lose the draft."""
    b = brand()
    payload = {
        "teks_iklan": {
            "hook": creative.hook,
            "primary_text": creative.primary_text,
            "headline": creative.headline,
            "cta": creative.cta,
        },
        "tag": {
            "concept": creative.concept,
            "angle": creative.angle,
            "format": creative.format,
            "awareness_level": creative.awareness_level,
        },
        "panduan_brand": {"nada": b["brand"]["tone"], "warna": b["brand"]["colors"],
                          "elak": b["brand"]["avoid"]},
        "audience": b["audience"],
    }
    images = [as_data_uri(image_bytes)] if image_bytes else []
    if not images:
        payload["nota"] = "Tiada gambar disertakan — nilai teks sahaja, beri artifak_ai skor 10."

    try:
        data = complete_json(
            SYSTEM_PROMPT,
            json.dumps(payload, ensure_ascii=False, indent=2),
            tier=MID,
            max_tokens=1200,
            images=images,
        )
    except Exception as exc:
        log.exception("Creative QA call failed")
        return QAResult(
            status="FLAGGED",
            summary="QA tak dapat dijalankan — semak sendiri sebelum guna.",
            error=str(exc)[:300],
        )

    raw_scores = data.get("skor") or {}
    scores = {dim: _score(raw_scores.get(dim)) for dim in DIMENSIONS}

    result = QAResult(
        scores=scores,
        issues=[str(i) for i in (data.get("masalah") or [])],
        fixes=[str(f) for f in (data.get("cara_betulkan") or [])],
        summary=str(data.get("ringkasan") or "").strip(),
    )
    result.status = "PASS" if not result.failing else "FAIL"
    return result


def _score(value) -> float:
    """Clamp whatever the model returned into 0-10; unusable -> 0 (fails safe)."""
    try:
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
