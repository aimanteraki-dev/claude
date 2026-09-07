"""OpenAI wrapper with the three cost tiers from CLAUDE.md section 3.

    cheap : tagging, formatting, alert wording, classification
    mid   : analysis, creative briefs, copywriting
    top   : monthly deep analysis ONLY — never in a daily loop

Hard rule enforced by convention throughout this codebase: prompts built here
receive numbers that were already computed by metrics.py. No prompt ever asks a
model to calculate, sum, average, or compare figures itself.
"""

from __future__ import annotations

import base64
import json
import logging
from functools import lru_cache
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from .config import get_settings

log = logging.getLogger(__name__)

CHEAP, MID, TOP = "cheap", "mid", "top"


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI

    return OpenAI(api_key=get_settings().openai_api_key)


def _model_for(tier: str) -> str:
    s = get_settings()
    return {CHEAP: s.model_cheap, MID: s.model_mid, TOP: s.model_top}[tier]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30), reraise=True)
def complete(
    system: str,
    user: str,
    tier: str = MID,
    max_tokens: int = 1500,
    images: list[str] | None = None,
) -> str:
    """One-shot completion. `images` are URLs or data URIs for vision calls."""
    content: Any = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": url}} for url in images
        ]

    resp = _client().chat.completions.create(
        model=_model_for(tier),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        max_completion_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def complete_json(
    system: str,
    user: str,
    tier: str = MID,
    max_tokens: int = 1500,
    images: list[str] | None = None,
) -> dict:
    """Completion constrained to a JSON object, parsed before returning."""
    content: Any = user
    if images:
        content = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": url}} for url in images
        ]

    resp = _client().chat.completions.create(
        model=_model_for(tier),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=max_tokens,
    )
    raw = (resp.choices[0].message.content or "{}").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.error("Model returned non-JSON despite json_object mode: %s", raw[:500])
        raise


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=2, min=2, max=20), reraise=True)
def generate_image(prompt: str, size: str = "1024x1536") -> bytes:
    """Generate one image. Default size is the closest 4:5-ish Meta feed ratio."""
    s = get_settings()
    resp = _client().images.generate(model=s.model_image, prompt=prompt, size=size, n=1)
    b64 = resp.data[0].b64_json
    if not b64:
        raise RuntimeError("Image API returned no image data")
    return base64.b64decode(b64)


def as_data_uri(image_bytes: bytes) -> str:
    """For handing a freshly generated image to a vision model (Creative QA)."""
    return "data:image/png;base64," + base64.b64encode(image_bytes).decode()
