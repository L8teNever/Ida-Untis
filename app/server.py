"""Ida-Untis MCP Server.

Stellt WebUntis-Stundenplandaten (Ausfälle, Vertretungen, Raum-/Lehrerwechsel,
Klassen/Lehrer/Räume/Fächer) als MCP-Tools über Streamable HTTP bereit, damit
Claude sie per Remote-MCP-Verbindung (z.B. über einen Cloudflare Tunnel) nutzen
kann. Der Endpunkt ist per Shared-Secret-Token abgesichert (siehe app/auth.py).
"""

from __future__ import annotations

import logging
from typing import Optional

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
    """Listet alle Lehrkraefte der Schule mit Kuerzel, Vor- und Nachname auf."""
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
def stundenplan(
    von: str,
    bis: str,
    klasse: Optional[str] = None,
    lehrer: Optional[str] = None,
    raum: Optional[str] = None,
) -> list[dict]:
    """Kompletter Stundenplan fuer einen Zeitraum.

    von/bis: Datum im Format JJJJ-MM-TT (z.B. 2026-07-21).
    Genau eines von klasse/lehrer/raum angeben (Name oder Kuerzel), oder alle
    weglassen fuer den Stundenplan des in UNTIS_USERNAME hinterlegten Kontos.
    Jeder Eintrag enthaelt Status (regulaer/ausgefallen/geaendert), Fach,
    Lehrer, Klasse und Raum -- inklusive urspruenglichem Lehrer/Raum bei
    Aenderungen.
    """
    return client.stundenplan(von, bis, klasse, lehrer, raum)


@mcp.tool()
def ausfaelle(
    von: str, bis: str, klasse: Optional[str] = None, lehrer: Optional[str] = None
) -> list[dict]:
    """Nur die ausgefallenen Stunden in einem Zeitraum (Format JJJJ-MM-TT).

    klasse/lehrer optional zum Filtern auf eine Klasse oder Lehrkraft.
    """
    return client.ausfaelle(von, bis, klasse, lehrer)


@mcp.tool()
def aenderungen(
    von: str, bis: str, klasse: Optional[str] = None, lehrer: Optional[str] = None
) -> list[dict]:
    """Nur die geaenderten Stunden (Raum-/Lehrerwechsel, Verlegung) in einem
    Zeitraum. Enthaelt jeweils sowohl den neuen als auch den urspruenglichen
    Lehrer/Raum.
    """
    return client.aenderungen(von, bis, klasse, lehrer)


@mcp.tool()
def vertretungen(von: str, bis: str) -> list[dict]:
    """Rohe schulweite Vertretungsliste von WebUntis fuer einen Zeitraum
    (alle Klassen, Format JJJJ-MM-TT).
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
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port, log_level="info")


if __name__ == "__main__":
    main()
