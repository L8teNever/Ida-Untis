# Ida-Untis

Ein MCP-Server (Model Context Protocol), der WebUntis-Stundenplandaten für
Claude bereitstellt: ausgefallene Stunden, Vertretungen, Raum-/Lehrerwechsel,
Klassen, Lehrer, Räume, Fächer und Ferien. Läuft als Docker-Container und wird
über einen bestehenden Cloudflare Tunnel unter einer eigenen Domain erreichbar
gemacht.

## Architektur

```
Claude  --https-->  Cloudflare Tunnel (öffentliche Domain)
                            |
                            v
                 127.0.0.1:8000 auf deinem Server
                            |
                            v
                 Docker-Container "ida-untis-mcp"
                            |
                            v
                      WebUntis JSON-API
```

Der Container published seinen Port **nur auf `127.0.0.1`** -- er ist von
außen nicht direkt erreichbar, sondern nur über den bereits auf dem Server
laufenden `cloudflared`-Prozess. Zusätzlich verlangt der Server bei jeder
Anfrage ein geheimes Token (`MCP_AUTH_TOKEN`). Beides zusammen sorgt dafür,
dass nicht "jeder" an die Domain kommt, selbst wenn die Domain bekannt ist.

## Voraussetzungen

- Docker + Docker Compose auf dem Server
- Ein bereits eingerichteter und verbundener Cloudflare Tunnel auf diesem Server
- Ein WebUntis-Zugang (Schüler-, Eltern- oder Lehrer-Login)
- Ein GitHub-Repo namens `Ida-Untis` (dieses hier) mit Actions aktiviert

## 1. Einrichten

```bash
git clone https://github.com/<dein-user>/Ida-Untis.git
cd Ida-Untis
cp .env.example .env
```

`.env` ausfüllen:

| Variable | Bedeutung |
|---|---|
| `UNTIS_SERVER` | Nur der Host, z.B. `nessa.webuntis.com` (aus der Browser-URL, wenn in WebUntis eingeloggt) |
| `UNTIS_SCHOOL` | Schulname/-kürzel wie bei der Schulauswahl in WebUntis |
| `UNTIS_USERNAME` / `UNTIS_PASSWORD` | Normaler WebUntis-Login |
| `UNTIS_KLASSE` | Kürzel der einen Klasse, auf die der Server fest eingestellt ist (z.B. `1T`) -- alle Tools liefern ausschließlich Daten dieser Klasse |
| `MCP_AUTH_TOKEN` | Langes Zufalls-Token, das Claude beim Verbinden mitschicken muss. Erzeugen mit `openssl rand -hex 32` |
| `MCP_PORT` | Lokaler Port (Standard `8000`) |
| `GITHUB_OWNER` | Dein GitHub-Benutzername in Kleinbuchstaben (für das Image aus GHCR) |

`.env` bleibt lokal auf dem Server und wird **nicht** committet (steht in
`.gitignore`).

## 2. Image bauen lassen (GitHub Actions)

Bei jedem Push auf `main` baut `.github/workflows/docker-publish.yml` das
Docker-Image automatisch und veröffentlicht es nach
`ghcr.io/<dein-user>/ida-untis:latest`.

Damit `docker compose` das Image ohne Login ziehen kann, muss das Package
beim ersten Mal auf öffentlich gestellt werden:
GitHub -> dein Profil -> **Packages** -> `ida-untis` -> **Package settings**
-> **Change visibility** -> **Public**.

Alternativ (wenn privat bleiben soll): auf dem Server einmalig
`docker login ghcr.io -u <dein-user>` mit einem Personal Access Token
(Scope `read:packages`) ausführen.

## 3. Starten

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

Der Healthcheck prüft `http://127.0.0.1:8000/healthz`. Mit
`docker compose ps` sollte der Container als `healthy` erscheinen.

## 4. An den bestehenden Cloudflare Tunnel anbinden

Kein neuer Tunnel nötig -- nur eine zusätzliche Ingress-Regel im bestehenden
Tunnel, die auf den lokalen Port zeigt.

**Dashboard (Zero Trust -> Networks -> Tunnels -> dein Tunnel -> Public Hostname):**
- Hostname: z.B. `untis.deine-domain.de`
- Service: `http://localhost:8000`

**Oder per `config.yml`, falls du den Tunnel so verwaltest:**

```yaml
ingress:
  - hostname: untis.deine-domain.de
    service: http://localhost:8000
  - service: http_status:404
```

Danach `cloudflared` neu laden bzw. den Tunnel-Dienst neu starten, damit die
neue Ingress-Regel greift.

Optional für eine zusätzliche Sicherheitsebene: Die Hostname per
**Cloudflare Access** (Zero Trust) zusätzlich auf bestimmte E-Mail-Adressen
oder ein Service-Token einschränken -- dann muss man sowohl an Cloudflare
Access als auch am `MCP_AUTH_TOKEN` vorbei.

## 5. Mit Claude verbinden

Der MCP-Endpunkt liegt unter `https://untis.deine-domain.de/mcp` (Streamable
HTTP). Das Token kann auf drei Arten mitgeschickt werden -- je nachdem, was
der jeweilige Claude-Client unterstützt:

- Header `Authorization: Bearer <MCP_AUTH_TOKEN>`
- Header `X-API-Key: <MCP_AUTH_TOKEN>`
- Query-Parameter `?token=<MCP_AUTH_TOKEN>` (falls der Client nur eine reine
  URL akzeptiert, z.B. manche Custom-Connector-UIs)

**Claude Code CLI:**

```bash
claude mcp add --transport http ida-untis \
  https://untis.deine-domain.de/mcp \
  --header "Authorization: Bearer <MCP_AUTH_TOKEN>"
```

**claude.ai / Claude Desktop (Custom Connector):**
Einstellungen -> Connectors -> Add custom connector -> URL eintragen. Falls
dort kein Header konfigurierbar ist, die Token-Variante als Query-Parameter
verwenden: `https://untis.deine-domain.de/mcp?token=<MCP_AUTH_TOKEN>`.

## Verfügbare Tools

`stundenplan`, `ausfaelle`, `aenderungen` und `vertretungen` sind fest auf
die in `UNTIS_KLASSE` konfigurierte Klasse eingestellt -- es gibt keinen
Parameter, um eine andere Klasse abzufragen. Das ist bewusst so (Scope-Lock
auf eine Klasse) und umgeht nebenbei auch ein WebUntis-Problem: manche
Accounts haben für die generische "eigener Stundenplan"-Abfrage keine
Berechtigung (Fehler `no right for timetable`), der Klassen-Stundenplan
funktioniert aber unabhängig davon.

| Tool | Zweck |
|---|---|
| `stundenplan(von, bis)` | Kompletter Stundenplan der konfigurierten Klasse im Zeitraum |
| `ausfaelle(von, bis)` | Nur ausgefallene Stunden |
| `aenderungen(von, bis)` | Nur geänderte Stunden (Raum-/Lehrerwechsel) |
| `vertretungen(von, bis)` | Vertretungen, gefiltert auf die konfigurierte Klasse |
| `klassen_liste()` | Alle Klassen der Schule (nur Namen/IDs, keine Stundenplandaten) |
| `lehrer_liste()` | Kürzel aller Lehrkräfte der Schule (keine vollen Namen, Datenschutz) |
| `raeume_liste()` | Alle Räume der Schule |
| `faecher_liste()` | Alle Fächer der Schule |
| `ferien_liste()` | Ferien/Feiertage |

Datumsangaben immer als `JJJJ-MM-TT`, z.B. `2026-07-21`.

## Lokal testen ohne Cloudflare

```bash
docker compose up -d
curl -H "Authorization: Bearer $MCP_AUTH_TOKEN" http://127.0.0.1:8000/healthz
```

## Troubleshooting

- **Container startet nicht / beendet sofort**: `docker compose logs` prüfen
  -- meist fehlt eine Pflicht-Variable in `.env` (klare Fehlermeldung beim
  Start).
- **Login bei WebUntis schlägt fehl**: `UNTIS_SERVER`/`UNTIS_SCHOOL` prüfen
  (Server nur als Host, ohne `https://`), Zugangsdaten in WebUntis selbst
  testen.
- **Claude bekommt 401**: Token in der Client-Konfiguration und in `.env`
  vergleichen (Groß-/Kleinschreibung, keine Leerzeichen).
- **GHCR-Image lässt sich nicht pullen**: Package-Sichtbarkeit prüfen (siehe
  Schritt 2) oder `docker login ghcr.io` auf dem Server ausführen.
