"""Ida-Untis MCP Server.

Stellt WebUntis-Stundenplandaten (Ausfälle, Vertretungen, Raum-/Lehrerwechsel,
Klassen/Lehrer/Räume/Fächer) als MCP-Tools über Streamable HTTP bereit, damit
Claude sie per Remote-MCP-Verbindung (z.B. über einen Cloudflare Tunnel) nutzen
kann. Der Endpunkt ist per Shared-Secret-Token abgesichert (siehe app/auth.py).
"""

from __future__ import annotations

import logging

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from app.auth import BearerAuthMiddleware
from app.config import load_settings
from app.untis_client import UntisClient

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("ida-untis")

settings = load_settings()
client = UntisClient(settings)

mcp = FastMCP(
    "Ida-Untis",
    instructions=(
        "Werkzeuge fuer den WebUntis-Stundenplan. Nutze sie, um Ausfaelle, "
        "Vertretungen, Raum- und Lehrerwechsel sowie den regulaeren Stundenplan "
        "fuer ein Datum oder einen Zeitraum abzufragen. Datumsangaben immer im "
        "Format JJJJ-MM-TT (z.B. 2026-07-21)."
    ),
    host=settings.mcp_host,
    port=settings.mcp_port,
)


@mcp.tool()
def klassen_liste() -> list[dict]:
    """Listet alle Klassen der Schule mit id, Kurzname und Langname auf."""
    return client.list_klassen()


@mcp.tool()
def lehrer_liste() -> list[dict]:
    """Listet die Kuerzel aller Lehrkraefte der Schule auf (keine vollen Namen, Datenschutz)."""
    return client.list_lehrer()


@mcp.tool()
def raeume_liste() -> list[dict]:
    """Listet alle Raeume der Schule auf."""
    return client.list_raeume()


@mcp.tool()
def faecher_liste() -> list[dict]:
    """Listet alle Unterrichtsfaecher der Schule auf."""
    return client.list_faecher()


@mcp.tool()
def ferien_liste() -> list[dict]:
    """Listet alle Schulferien/Feiertage mit Zeitraum auf."""
    return client.list_ferien()


@mcp.tool()
def stundenplan(von: str, bis: str) -> list[dict]:
    """Kompletter Stundenplan fuer einen Zeitraum, ausschliesslich fuer die
    in UNTIS_KLASSE konfigurierte Klasse -- es kann keine andere Klasse
    abgefragt werden.

    von/bis: Datum im Format JJJJ-MM-TT (z.B. 2026-07-21).
    Jeder Eintrag enthaelt Status (regulaer/ausgefallen/geaendert), Fach,
    Lehrer, Klasse und Raum -- inklusive urspruenglichem Lehrer/Raum bei
    Aenderungen.
    """
    return client.stundenplan(von, bis)


@mcp.tool()
def ausfaelle(von: str, bis: str) -> list[dict]:
    """Nur die ausgefallenen Stunden der konfigurierten Klasse in einem
    Zeitraum (Format JJJJ-MM-TT).
    """
    return client.ausfaelle(von, bis)


@mcp.tool()
def aenderungen(von: str, bis: str) -> list[dict]:
    """Nur die geaenderten Stunden (Raum-/Lehrerwechsel, Verlegung) der
    konfigurierten Klasse in einem Zeitraum. Enthaelt jeweils sowohl den
    neuen als auch den urspruenglichen Lehrer/Raum.
    """
    return client.aenderungen(von, bis)


@mcp.tool()
def vertretungen(von: str, bis: str) -> list[dict]:
    """Vertretungsliste von WebUntis fuer einen Zeitraum (Format JJJJ-MM-TT),
    gefiltert auf die in UNTIS_KLASSE konfigurierte Klasse.
    """
    return client.vertretungen(von, bis)


async def healthz(request):
    return JSONResponse({"status": "ok"})


def build_app():
    app = mcp.streamable_http_app()
    app.add_route("/healthz", healthz, methods=["GET"])
    app.add_middleware(BearerAuthMiddleware, token=settings.mcp_auth_token)
    return app


def main() -> None:
    app = build_app()
    log.info(
        "Ida-Untis MCP Server startet auf %s:%s (Endpunkt: /mcp, Health: /healthz)",
        settings.mcp_host,
        settings.mcp_port,
    )
    # access_log=False: uvicorn wuerde sonst jede Request-Zeile inkl. vollem
    # Pfad loggen -- und damit ein per ?token= mitgeschicktes MCP_AUTH_TOKEN
    # im Klartext in die Docker-Logs schreiben.
    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
