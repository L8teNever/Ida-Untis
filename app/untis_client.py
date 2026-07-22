"""Dünner, robuster Wrapper um python-webuntis für den MCP Server.

Jeder Aufruf öffnet eine eigene WebUntis-Session und schließt sie danach
wieder -- das ist bei der geringen Nutzungsfrequenz (ein Mensch fragt ab
und zu Claude) einfacher und robuster als eine langlebige Session über
Prozessgrenzen/Threads hinweg am Leben zu halten. Ein Lock serialisiert
die Zugriffe, weil manche WebUntis-Server parallele Logins des gleichen
Kontos nicht mögen.
"""

from __future__ import annotations

import datetime as dt
import threading
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional

import webuntis
import webuntis.errors

from app.config import Settings


class UntisError(RuntimeError):
    """Fehler, die 1:1 als verständliche Meldung an Claude zurückgehen sollen."""


def _parse_date(value: str, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise UntisError(
            f"'{value}' ist kein gültiges Datum für {field_name}. "
            "Bitte im Format JJJJ-MM-TT angeben, z.B. 2026-07-21."
        ) from exc


def _safe(obj: Any, attr: str, default: Any = "") -> Any:
    try:
        value = getattr(obj, attr)
    except Exception:
        return default
    return value if value is not None else default


def _element_names(elements: Iterable[Any]) -> list[str]:
    names = []
    for el in elements or []:
        short = _safe(el, "name", "")
        long = _safe(el, "long_name", "")
        if long and long != short:
            names.append(f"{short} ({long})")
        else:
            names.append(short or "?")
    return names


def _resolve_id(list_result: Any, needle: str, kind: str) -> int:
    """Findet die id eines Elements (Klasse/Lehrer/Raum) anhand eines Namens.

    Versucht zuerst eine exakte Übereinstimmung mit dem Kurznamen, danach
    case-insensitive auf Kurz- und Langname, danach eine Teilstring-Suche.
    """
    exact = list_result.filter(name=needle)
    if exact:
        return exact[0].id

    needle_lower = needle.strip().lower()
    candidates = []
    for el in list_result:
        short = str(_safe(el, "name", "")).lower()
        long = str(_safe(el, "long_name", "")).lower()
        fore = str(_safe(el, "fore_name", "")).lower()
        full = f"{fore} {long}".strip()
        if needle_lower == short or needle_lower == long or needle_lower == full:
            return el.id
        if needle_lower in short or needle_lower in long or needle_lower in full:
            candidates.append(el)

    if len(candidates) == 1:
        return candidates[0].id

    available = ", ".join(_element_names(list_result)[:30])
    raise UntisError(
        f"{kind} '{needle}' wurde nicht eindeutig gefunden. "
        f"Verfügbare {kind}n (Auswahl): {available}"
    )


def _serialize_period(period: Any) -> dict:
    code = str(_safe(period, "code", "")) or "regular"
    entry = {
        "start": _safe(period, "start").isoformat() if _safe(period, "start", None) else None,
        "end": _safe(period, "end").isoformat() if _safe(period, "end", None) else None,
        "status": {
            "regular": "regulär",
            "cancelled": "ausgefallen",
            "irregular": "geändert",
        }.get(code, code),
        "faecher": _element_names(_safe(period, "subjects", [])),
        "lehrer": _element_names(_safe(period, "teachers", [])),
        "klassen": _element_names(_safe(period, "klassen", [])),
        "raeume": _element_names(_safe(period, "rooms", [])),
    }
    original_teachers = _element_names(_safe(period, "original_teachers", []))
    original_rooms = _element_names(_safe(period, "original_rooms", []))
    if original_teachers and original_teachers != entry["lehrer"]:
        entry["urspruenglicher_lehrer"] = original_teachers
    if original_rooms and original_rooms != entry["raeume"]:
        entry["urspruenglicher_raum"] = original_rooms
    info = _safe(period, "info", "") or _safe(period, "lstext", "")
    if info:
        entry["info"] = info
    return entry


class UntisClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._klasse_id: Optional[int] = None

    def _resolve_klasse_id(self, s: Any) -> int:
        """Löst UNTIS_KLASSE einmalig zu einer id auf und cached sie.

        Die id einer Klasse ändert sich nicht zwischen Sessions, daher muss
        s.klassen() nicht bei jedem Aufruf erneut abgefragt werden.
        """
        if self._klasse_id is None:
            self._klasse_id = _resolve_id(
                s.klassen(), self._settings.untis_klasse, "Klasse"
            )
        return self._klasse_id

    @contextmanager
    def _session(self) -> Iterator[Any]:
        with self._lock:
            s = webuntis.Session(
                server=self._settings.untis_server,
                school=self._settings.untis_school,
                username=self._settings.untis_username,
                password=self._settings.untis_password,
                useragent=self._settings.untis_useragent,
            )
            try:
                s.login()
            except webuntis.errors.BadCredentialsError as exc:
                raise UntisError(
                    "Login bei WebUntis fehlgeschlagen: Benutzername/Passwort falsch "
                    "(UNTIS_USERNAME/UNTIS_PASSWORD prüfen)."
                ) from exc
            except webuntis.errors.RemoteError as exc:
                raise UntisError(f"WebUntis hat den Login abgelehnt: {exc}") from exc
            except Exception as exc:  # Netzwerk, falscher Server/Schule, ...
                raise UntisError(
                    f"Verbindung zu WebUntis fehlgeschlagen (UNTIS_SERVER/UNTIS_SCHOOL prüfen): {exc}"
                ) from exc

            try:
                yield s
            except webuntis.errors.RemoteError as exc:
                raise UntisError(f"WebUntis-Fehler: {exc}") from exc
            finally:
                s.logout(suppress_errors=True)

    def list_klassen(self) -> list[dict]:
        with self._session() as s:
            return [
                {"id": k.id, "name": k.name, "langname": _safe(k, "long_name", "")}
                for k in s.klassen()
            ]

    def list_lehrer(self) -> list[dict]:
        with self._session() as s:
            return [
                {
                    "id": t.id,
                    "kuerzel": t.name,
                    "vorname": _safe(t, "fore_name", ""),
                    "nachname": _safe(t, "long_name", ""),
                }
                for t in s.teachers()
            ]

    def list_raeume(self) -> list[dict]:
        with self._session() as s:
            return [
                {"id": r.id, "name": r.name, "langname": _safe(r, "long_name", "")}
                for r in s.rooms()
            ]

    def list_faecher(self) -> list[dict]:
        with self._session() as s:
            return [
                {"id": f.id, "kuerzel": f.name, "langname": _safe(f, "long_name", "")}
                for f in s.subjects()
            ]

    def list_ferien(self) -> list[dict]:
        with self._session() as s:
            return [
                {
                    "name": _safe(h, "long_name", "") or _safe(h, "name", ""),
                    "start": h.start.isoformat(),
                    "ende": h.end.isoformat(),
                }
                for h in s.holidays()
            ]

    def _timetable(self, von: str, bis: str) -> list[dict]:
        """Stundenplan ausschliesslich fuer die in UNTIS_KLASSE konfigurierte
        Klasse. Kein Fallback auf my_timetable (manche WebUntis-Accounts
        haben dafuer keine Berechtigung -- Fehler "no right for timetable")
        und keine Moeglichkeit, eine andere Klasse abzufragen.
        """
        start = _parse_date(von, "von")
        end = _parse_date(bis, "bis")
        if end < start:
            raise UntisError("'bis' darf nicht vor 'von' liegen.")

        with self._session() as s:
            klasse_id = self._resolve_klasse_id(s)
            periods = s.timetable(start=start, end=end, klasse=klasse_id)
            return [_serialize_period(p) for p in periods]

    def stundenplan(self, von: str, bis: str) -> list[dict]:
        return self._timetable(von, bis)

    def ausfaelle(self, von: str, bis: str) -> list[dict]:
        periods = self._timetable(von, bis)
        return [p for p in periods if p["status"] == "ausgefallen"]

    def aenderungen(self, von: str, bis: str) -> list[dict]:
        periods = self._timetable(von, bis)
        return [p for p in periods if p["status"] == "geändert"]

    def vertretungen(self, von: str, bis: str) -> list[dict]:
        """Vertretungen, gefiltert auf die in UNTIS_KLASSE konfigurierte Klasse."""
        start = _parse_date(von, "von")
        end = _parse_date(bis, "bis")
        with self._session() as s:
            klasse_id = self._resolve_klasse_id(s)
            subs = s.substitutions(start=start, end=end)
            out = []
            for sub in subs:
                klassen = _safe(sub, "klassen", [])
                if not any(_safe(k, "id", None) == klasse_id for k in klassen):
                    continue
                out.append(
                    {
                        "datum": _safe(sub, "start").isoformat() if _safe(sub, "start", None) else None,
                        "typ": _safe(sub, "type", ""),
                        "faecher": _element_names(_safe(sub, "subjects", [])),
                        "klassen": _element_names(klassen),
                        "lehrer": _element_names(_safe(sub, "teachers", [])),
                        "urspruenglicher_lehrer": _element_names(
                            _safe(sub, "original_teachers", [])
                        ),
                        "raeume": _element_names(_safe(sub, "rooms", [])),
                        "urspruenglicher_raum": _element_names(
                            _safe(sub, "original_rooms", [])
                        ),
                        "text": _safe(sub, "text", ""),
                    }
                )
            return out
