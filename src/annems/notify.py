"""Telegram notifications. The only interface humans use in V1 (no dashboard).

Ref: CLAUDE.md principle 6 ("Fail loudly") and section 9 (Telegram is the UI).
"""

from __future__ import annotations

import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import get_settings

log = logging.getLogger(__name__)

TELEGRAM_MAX_CHARS = 4096


class Recipient:
    AIMAN = "aiman"
    IBU = "ibu"
    BOTH = "both"


def _chat_ids(to: str) -> list[str]:
    s = get_settings()
    if to == Recipient.AIMAN:
        return [s.telegram_chat_id_aiman]
    if to == Recipient.IBU:
        return [s.telegram_chat_id_ibu] if s.telegram_chat_id_ibu else []
    ids = [s.telegram_chat_id_aiman]
    if s.telegram_chat_id_ibu:
        ids.append(s.telegram_chat_id_ibu)
    return ids


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def _post(method: str, payload: dict, files: dict | None = None) -> dict:
    s = get_settings()
    url = f"https://api.telegram.org/bot{s.telegram_bot_token}/{method}"
    with httpx.Client(timeout=30) as client:
        resp = client.post(url, data=payload, files=files)
        resp.raise_for_status()
        return resp.json()


def send(text: str, to: str = Recipient.AIMAN, markdown: bool = True) -> None:
    """Send a message, splitting anything over Telegram's 4096-char limit."""
    s = get_settings()
    if s.dry_run:
        log.info("[DRY_RUN] telegram -> %s:\n%s", to, text)
        return

    for chat_id in _chat_ids(to):
        for chunk in _split(text):
            payload = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
            if markdown:
                payload["parse_mode"] = "Markdown"
            try:
                _post("sendMessage", payload)
            except Exception:
                # Markdown parse errors are the usual culprit; retry as plain text
                # rather than losing the message entirely.
                log.exception("Markdown send failed, retrying as plain text")
                _post("sendMessage", {"chat_id": chat_id, "text": chunk})


def send_photo(image_bytes: bytes, caption: str = "", to: str = Recipient.AIMAN) -> None:
    s = get_settings()
    if s.dry_run:
        log.info("[DRY_RUN] telegram photo -> %s (%d bytes): %s", to, len(image_bytes), caption)
        return
    for chat_id in _chat_ids(to):
        _post(
            "sendPhoto",
            {"chat_id": chat_id, "caption": caption[:1024]},
            files={"photo": ("creative.png", image_bytes, "image/png")},
        )


def alert_failure(where: str, error: Exception | str) -> None:
    """Silent failure is the worst failure. Always reaches Aiman.

    Never raises: an alert that explodes would hide the original error.
    """
    text = (
        "🚨 *SISTEM GAGAL*\n"
        f"Bahagian: `{where}`\n"
        f"Ralat: `{str(error)[:600]}`\n\n"
        "Data hari ini mungkin tak lengkap. Cek log Railway."
    )
    try:
        send(text, to=Recipient.AIMAN)
    except Exception:
        log.exception("CRITICAL: failure alert itself failed for %s", where)


def _split(text: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Split on line boundaries where possible so tables stay readable."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            # A single line longer than the limit gets hard-split.
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
