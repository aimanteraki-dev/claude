"""Telegram webhook — the only user interface in V1 (no dashboard, section 9).

Commands:
    /report            morning report for yesterday, on demand
    /weekly            weekly summary
    /creative [n]      Agents 4+5 produce n QA'd options (default 3)
    /status            last agent runs, so failures are visible
    /alerts            alerts raised in the last 24 hours
    /help

Security: Telegram's secret-token header is verified on every request, and only
the two configured chat ids may issue commands. An unknown chat gets nothing.

Approvals: pressing Approve/Reject records the decision in `approvals`. It does
NOT publish anything — V1 has read-only Meta access by design (section 6).
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from fastapi import FastAPI, Header, HTTPException, Request

from . import db, logging_setup, notify
from .config import get_settings, today_myt

logging_setup.setup()
log = logging.getLogger(__name__)

app = FastAPI(title="Annems AI Marketing Department", version="1.0.0")

WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

HELP_TEXT = """*Annems AI Marketing Department*

/report — laporan pagi (data semalam)
/weekly — ringkasan mingguan
/creative [n] — jana n pilihan creative (default 3)
/status — status run agent terkini
/alerts — alert 24 jam lepas
/help — mesej ini

Nota: sistem ini *tak* publish, pause, atau ubah budget di Meta. Semua tindakan
itu manual dalam Ads Manager."""


def _allowed_chats() -> set[str]:
    s = get_settings()
    return {c for c in (s.telegram_chat_id_aiman, s.telegram_chat_id_ibu) if c}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if WEBHOOK_SECRET and x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="bad secret token")

    update = await request.json()

    if "callback_query" in update:
        return _handle_callback(update["callback_query"])

    message = update.get("message") or update.get("edited_message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    text = (message.get("text") or "").strip()

    if chat_id not in _allowed_chats():
        log.warning("Ignoring update from unauthorised chat %s", chat_id)
        return {"ok": True}
    if not text.startswith("/"):
        return {"ok": True}

    parts = text.split()
    command = parts[0].split("@")[0].lower()
    args = parts[1:]

    try:
        _dispatch(command, args, chat_id)
    except Exception as exc:
        log.exception("Command %s failed", command)
        notify.send(f"❌ Arahan `{command}` gagal: `{str(exc)[:300]}`", to=notify.Recipient.AIMAN)
    return {"ok": True}


def _dispatch(command: str, args: list[str], chat_id: str) -> None:
    if command == "/help" or command == "/start":
        notify.send(HELP_TEXT, to=notify.Recipient.AIMAN)

    elif command == "/report":
        from .agents import reporter

        reporter.run_daily(to=notify.Recipient.AIMAN)

    elif command == "/weekly":
        from .agents import reporter

        reporter.run_weekly(to=notify.Recipient.AIMAN)

    elif command == "/creative":
        from .agents import creative_factory

        n = 3
        if args and args[0].isdigit():
            n = max(1, min(5, int(args[0])))
        concept = " ".join(args[1:]) if len(args) > 1 else None
        creative_factory.run(n=n, concept=concept)

    elif command == "/status":
        notify.send(_status_text(), to=notify.Recipient.AIMAN)

    elif command == "/alerts":
        notify.send(_alerts_text(), to=notify.Recipient.AIMAN)

    else:
        notify.send(f"Arahan tak dikenali: `{command}`\n\n{HELP_TEXT}", to=notify.Recipient.AIMAN)


def _status_text() -> str:
    try:
        res = (
            db.get_client()
            .table("agent_runs")
            .select("agent,started_at,status,error,output_summary")
            .order("started_at", desc=True)
            .limit(10)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:
        return f"Tak dapat baca agent_runs: `{str(exc)[:200]}`"

    if not rows:
        return "Tiada run direkodkan lagi."

    icon = {"ok": "✅", "error": "❌", "running": "⏳"}
    lines = ["*Run agent terkini*", ""]
    for r in rows:
        started = str(r.get("started_at", ""))[:16].replace("T", " ")
        lines.append(f"{icon.get(r.get('status'), '•')} `{r.get('agent')}` — {started}")
        if r.get("status") == "error" and r.get("error"):
            lines.append(f"   ↳ {str(r['error'])[:150]}")
    return "\n".join(lines)


def _alerts_text() -> str:
    cutoff = today_myt() - timedelta(days=1)
    try:
        res = (
            db.get_client()
            .table("alerts")
            .select("rule,severity,message,sent_at")
            .gte("sent_at", cutoff.isoformat())
            .order("sent_at", desc=True)
            .limit(10)
            .execute()
        )
        rows = res.data or []
    except Exception as exc:
        return f"Tak dapat baca alerts: `{str(exc)[:200]}`"

    if not rows:
        return "✅ Tiada alert dalam 24 jam lepas."
    lines = ["*Alert 24 jam lepas*", ""]
    for r in rows:
        lines.append(f"• `{r.get('rule')}` ({r.get('severity')})")
    return "\n".join(lines)


def _handle_callback(callback: dict) -> dict:
    """Approve/reject buttons. Records the decision only — nothing is published."""
    data = callback.get("data") or ""
    user = (callback.get("from") or {}).get("username") or str(
        (callback.get("from") or {}).get("id", "unknown")
    )
    if ":" not in data:
        return {"ok": True}

    decision, approval_id = data.split(":", 1)
    if decision not in {"approved", "rejected"}:
        return {"ok": True}

    try:
        db.decide_approval(approval_id, decision, user)
        notify.send(
            f"Direkod: *{decision}* oleh @{user}.\n"
            "Ingat — publish/pause masih manual dalam Ads Manager.",
            to=notify.Recipient.AIMAN,
        )
    except Exception:
        log.exception("Could not record approval %s", approval_id)
    return {"ok": True}
