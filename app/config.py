"""Konfiguration des Ida-Untis MCP Servers, komplett über Umgebungsvariablen."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Umgebungsvariable {name} fehlt oder ist leer.")
    return value


def _optional(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


@dataclass(frozen=True)
class Settings:
    untis_school: str
    untis_username: str
    untis_password: str
    untis_server: str
    untis_useragent: str

    mcp_auth_token: str
    mcp_host: str
    mcp_port: int


def load_settings() -> Settings:
    try:
        untis_server = _require("UNTIS_SERVER")
        # Nutzer geben oft versehentlich eine volle URL an -- wir normalisieren auf den reinen Host.
        untis_server = (
            untis_server.replace("https://", "").replace("http://", "").split("/")[0]
        )

        mcp_auth_token = _require("MCP_AUTH_TOKEN")
        if len(mcp_auth_token) < 16:
            raise ConfigError(
                "MCP_AUTH_TOKEN ist zu kurz (mind. 16 Zeichen). "
                "Erzeuge z.B. mit: openssl rand -hex 32"
            )

        settings = Settings(
            untis_school=_require("UNTIS_SCHOOL"),
            untis_username=_require("UNTIS_USERNAME"),
            untis_password=_require("UNTIS_PASSWORD"),
            untis_server=untis_server,
            untis_useragent=_optional("UNTIS_USERAGENT", "Ida-Untis-MCP"),
            mcp_auth_token=mcp_auth_token,
            mcp_host=_optional("MCP_HOST", "0.0.0.0"),
            mcp_port=int(_optional("MCP_PORT", "8000")),
        )
    except ConfigError as exc:
        print(f"[Ida-Untis] Konfigurationsfehler: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    return settings
