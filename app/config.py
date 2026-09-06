from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "config.json"))


@dataclass
class Settings:
    polling_interval_seconds: int = int(os.environ.get("POLLING_INTERVAL_SECONDS", "300"))
    min_request_delay_seconds: float = float(os.environ.get("MIN_REQUEST_DELAY_SECONDS", "5"))
    min_margin_percent: float = float(os.environ.get("MIN_MARGIN_PERCENT", "15"))
    default_vend_multiplier: float = float(os.environ.get("DEFAULT_VEND_MULTIPLIER", "1.4"))
    database_path: str = os.environ.get("DATABASE_PATH", "data/stock_monitor.db")
    port: int = int(os.environ.get("PORT", "8080"))

    twilio_account_sid: str = os.environ.get("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.environ.get("TWILIO_AUTH_TOKEN", "")
    twilio_from_number: str = os.environ.get("TWILIO_FROM_NUMBER", "")
    twilio_to_number: str = os.environ.get("TWILIO_TO_NUMBER", "")

    retailers: list = field(default_factory=list)
    in_stock_keywords: list = field(default_factory=list)
    out_of_stock_keywords: list = field(default_factory=list)
    vend_overrides: dict = field(default_factory=dict)

    @property
    def sms_enabled(self) -> bool:
        return bool(
            self.twilio_account_sid
            and self.twilio_auth_token
            and self.twilio_from_number
            and self.twilio_to_number
        )


def load_settings() -> Settings:
    settings = Settings()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    settings.retailers = [r for r in raw.get("retailers", []) if r.get("enabled", True)]
    settings.in_stock_keywords = [k.lower() for k in raw.get("in_stock_keywords", [])]
    settings.out_of_stock_keywords = [k.lower() for k in raw.get("out_of_stock_keywords", [])]
    settings.vend_overrides = raw.get("vend_overrides", {})
    return settings
