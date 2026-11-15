"""Add-on options and data-directory handling (SPEC §11)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PRESETS = ("careful", "moderate")


@dataclass
class MqttOptions:
    host: str | None = None
    port: int = 1883
    username: str | None = None
    password: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.host)


@dataclass
class Options:
    sync_preset: str = "careful"
    recent_refresh_hours: float = 6
    backfill_until_year: int | None = None
    return_thresholds: list[int] = field(default_factory=lambda: [7, 2, 0])
    warranty_thresholds: list[int] = field(default_factory=lambda: [180, 90, 60, 30, 14, 5])
    default_warranty_months: int = 24
    mqtt: MqttOptions = field(default_factory=MqttOptions)
    domain: str = "amazon.it"
    login_port: int = 8098
    login_host: str = ""
    log_level: str = "info"

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> Options:
        raw = raw or {}
        o = cls()
        preset = str(raw.get("sync_preset") or o.sync_preset).lower()
        o.sync_preset = preset if preset in PRESETS else "careful"
        o.recent_refresh_hours = max(0.25, _num(raw.get("recent_refresh_hours"), o.recent_refresh_hours))
        year = raw.get("backfill_until_year")
        o.backfill_until_year = int(year) if str(year or "").strip().isdigit() else None
        o.return_thresholds = _int_list(raw.get("return_thresholds"), o.return_thresholds)
        o.warranty_thresholds = _int_list(raw.get("warranty_thresholds"), o.warranty_thresholds)
        o.default_warranty_months = int(_num(raw.get("default_warranty_months"), o.default_warranty_months))
        m = raw.get("mqtt") or {}
        o.mqtt = MqttOptions(
            host=(m.get("host") or None),
            port=int(_num(m.get("port"), 1883)),
            username=m.get("username") or None,
            password=m.get("password") or None,
        )
        adv = raw.get("advanced") or {}
        o.domain = str(adv.get("domain") or raw.get("domain") or o.domain)
        port = int(_num(raw.get("login_port"), o.login_port))
        o.login_port = port if 1 <= port <= 65535 else o.login_port
        o.login_host = str(raw.get("login_host") or adv.get("login_host") or "").strip()
        o.log_level = str(raw.get("log_level") or o.log_level).lower()
        return o


def _num(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int_list(v: Any, default: list[int]) -> list[int]:
    if not isinstance(v, list):
        return list(default)
    out = []
    for x in v:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return sorted(set(out), reverse=True) or list(default)


@dataclass
class Settings:
    data_dir: Path
    options: Options
    frontend_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "amazon_orders.db"

    @property
    def amazonorders_dir(self) -> Path:
        return self.data_dir / "amazonorders"

    @property
    def cookie_path(self) -> Path:
        return self.amazonorders_dir / f"cookies.{self.options.domain}.json"


def default_frontend_dir() -> Path:
    # <backend>/src/amazon_orders_ha/config.py -> <addon>/frontend/build
    return Path(__file__).resolve().parents[3] / "frontend" / "build"


def load_settings(data_dir: str | Path | None = None, options: Options | None = None) -> Settings:
    data = Path(data_dir or os.environ.get("AMAZON_ORDERS_DATA_DIR") or "/data")
    if options is None:
        opt_file = Path(os.environ.get("AMAZON_ORDERS_OPTIONS_FILE") or data / "options.json")
        raw = None
        if opt_file.is_file():
            try:
                raw = json.loads(opt_file.read_text())
            except (OSError, ValueError):
                log.warning("Cannot read options file %s, using defaults", opt_file)
        options = Options.from_dict(raw)
    fe = os.environ.get("AMAZON_ORDERS_FRONTEND_DIR")
    return Settings(data_dir=data, options=options, frontend_dir=Path(fe) if fe else default_frontend_dir())
