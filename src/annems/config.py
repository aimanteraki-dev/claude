"""Central configuration. All secrets come from environment variables.

Ref: CLAUDE.md section 3 (tech stack, secrets) and section 8 (coding standards).
Nothing else in the codebase should read os.environ directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"

MYT = ZoneInfo(os.getenv("TIMEZONE", "Asia/Kuala_Lumpur"))


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to .env and fill it in (see README)."
        )
    return value


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings, resolved lazily so imports never explode without a .env."""

    # OpenAI
    openai_api_key: str = field(default_factory=lambda: _require("OPENAI_API_KEY"))
    model_cheap: str = field(default_factory=lambda: os.getenv("MODEL_CHEAP", "gpt-5-mini"))
    model_mid: str = field(default_factory=lambda: os.getenv("MODEL_MID", "gpt-5"))
    model_top: str = field(default_factory=lambda: os.getenv("MODEL_TOP", "gpt-5"))
    model_image: str = field(default_factory=lambda: os.getenv("MODEL_IMAGE", "gpt-image-1"))

    # Supabase
    supabase_url: str = field(default_factory=lambda: _require("SUPABASE_URL"))
    supabase_service_key: str = field(default_factory=lambda: _require("SUPABASE_SERVICE_KEY"))

    # Meta (read-only in V1 — see CLAUDE.md section 6)
    meta_access_token: str = field(default_factory=lambda: _require("META_ACCESS_TOKEN"))
    meta_ad_account_id: str = field(default_factory=lambda: _require("META_AD_ACCOUNT_ID"))
    meta_api_version: str = field(default_factory=lambda: os.getenv("META_API_VERSION", "v21.0"))

    # GoHighLevel
    ghl_api_key: str = field(default_factory=lambda: _require("GHL_API_KEY"))
    ghl_location_id: str = field(default_factory=lambda: _require("GHL_LOCATION_ID"))
    ghl_api_base: str = field(
        default_factory=lambda: os.getenv("GHL_API_BASE", "https://services.leadconnectorhq.com")
    )

    # Telegram
    telegram_bot_token: str = field(default_factory=lambda: _require("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id_aiman: str = field(default_factory=lambda: _require("TELEGRAM_CHAT_ID_AIMAN"))
    telegram_chat_id_ibu: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID_IBU", ""))

    dry_run: bool = field(default_factory=lambda: _flag("DRY_RUN", False))

    @property
    def meta_graph_base(self) -> str:
        return f"https://graph.facebook.com/{self.meta_api_version}"

    @property
    def ad_account(self) -> str:
        """Meta wants the act_ prefix; tolerate it being supplied either way."""
        acct = self.meta_ad_account_id
        return acct if acct.startswith("act_") else f"act_{acct}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_thresholds() -> dict:
    """Alert thresholds and data-quality gates, from the single config file."""
    with THRESHOLDS_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def now_myt() -> datetime:
    """Current time in Malaysia. Everything scheduled/reported uses MYT."""
    return datetime.now(MYT)


def today_myt() -> date:
    return now_myt().date()
