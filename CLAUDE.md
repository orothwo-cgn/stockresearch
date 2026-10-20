# Aktienresearch

Marktbeobachtung und Recherche für ein privates Langfrist-Depot. Das System gibt Hinweise, Warnungen und Recherche-Ideen. Es handelt nie selbst.

## Anlagestil (Vorgaben des Nutzers)

- Horizont: langfristig, Altersvorsorge. Kein Daytrading. Drei bis sechs Monate auf einen Einstieg warten ist normal.
- Kernstrategie: in Panikphasen zukaufen. 2026 waren der Einbruch nach den Zollankündigungen im Rosengarten und die Iran-Eskalation die besten Einstiege. Hinweise sollen solche Phasen früh erkennen, nicht davor warnen.
- Zwei Körbe:
  - **Wachstum:** große Tech-Werte (Palantir, Alphabet, Meta, Microsoft), Cybersecurity (CrowdStrike, Cloudflare, Fortinet), KI-Infrastruktur (Vertiv).
  - **Dividende:** Versicherer (Allianz, Münchener Rück), Banken (HSBC), Konsum (P&G, Coca-Cola, Pepsi, McDonald's), Tabak (BAT, Altria), Öl. Dieser Korb soll ausgebaut werden.
- **Big Player** (Gruppe `big_player`): Amazon, Apple, Meta, Microsoft, Oracle, Alphabet. Frühwarnung (alle wichtig, je Abwärtsphase einmal): Stufen −10/−15/−20/−25/−30/−40 % vom Hoch, Bruch der 200T, relative Schwäche ≥ 10 Pp. ggü. Nasdaq 100 in einem Monat. Phase endet bei < 5 % unter Hoch. Zustand in `state.json` → `_bigplayer`. Rückblick: −10 % kam bei MSFT (19.11.2025), META (25.02.2025), GOOGL (07.02.2025) Wochen vor dem Tief; ca. 1 Meldung/Woche für alle sechs in unruhigen Jahren.
- **Palantir**: Frühwarnung wie Big Player plus Bruch der 90-Tage-Linie (`fruehwarnung: true, fruehwarnung_90t: true`, 11.10.2026). Einsatz laut Nutzer längst herausgenommen; kein Teilverkauf geplant, Momentum beobachten.
- **Wartebank** (Gruppe in config.yaml): Halbleiter-Ausrüstung/-Test (KLA, Onto Innovation, Qnity, Teradyne) und Astera Labs (seit 09.10.2026). Interessant, aber laut Nutzer aktuell zu teuer; erst bei deutlichem Rücksetzer melden/vorschlagen.
- Nicht gewollt: Hype-Titeln hinterherlaufen (genannt: Speicherchips wie Micron, auch TSMC). Lieber auf Rücksetzer warten.
- Neue Ideen: Marktkapitalisierung mindestens 10 Mrd. $, aus relevanten Branchen, gern bei Sektorrotation.
- Rückmeldungen zu Ideen (für künftige Recherchen beachten):
  - 08.10.2026: argenx nach dem Studienabbruch nachgekauft (langfristig überzeugt). Stryker "eher nichts für mich" → ausgeschlossen. NextEra Energy "klingt gut" → Watchlist Dividende. Versorger/Energie ja. (Korrektur 11.10.2026: Medizintechnik ist durchaus interessant. Stryker "erst einmal nicht, aber nicht völlig ignorieren" → Gruppe `zurueckgestellt`: still beobachten, nicht aktiv vorschlagen, nur bei wesentlichen Neuigkeiten erwähnen (Q3 am 29.10.). Im Depot: Intuitive Surgical, Abbott, EssilorLuxottica; auf der Beobachtungsliste u. a. Penumbra, Edwards, Boston Scientific.)
  - 09.10.2026: **Rüstung passt grundsätzlich nicht** (Rheinmetall, Hensoldt, DroneShield ausgeschlossen); keine Rüstungswerte als Ideen vorschlagen, auch nicht aus Screener oder YouTube. Palantir bleibt (gehalten, ausdrücklich gewünscht). Porsche AG verkauft (aus portfolio.csv entfernt, bis zum nächsten Depot-Export).
  - 15.10.2026: **Autowerte aktuell eher nicht interessant**; ausgeschlossen sind VW, Porsche Holding, Ferrari, Daimler Truck, Hella, Tesla, BYD. **BMW, Mercedes und Porsche AG bleiben** auf Wunsch in der Beobachtung (Abstauberliste Europa). Keine weiteren Autowerte als Ideen vorschlagen. **XPeng** (im Depot, 24 Stück) sieht der Nutzer als **Roboteraktie** (humanoide Robotik), nicht als Autowert → Watchlist `beobachtung`; bei Robotik-Themen mit einordnen.
  - 19.10.2026: Netflix (im Depot) unter Abstauber-Limit 2; Nutzer wartet die Q3-Zahlen am 20.10. (nach US-Börsenschluss) ab. Im nächsten Lauf danach Zahlen und Kursreaktion einordnen.
  - argenx: Teilkauf 200 € am 08.10.2026; These = Stammgeschäft Vyvgart, Zöliakie (FB102) als Option. Keine Kaufzone gewünscht, Nutzer wartet die nächsten Wochen ab.

## Aufbau

- `config.yaml`: Indizes, Sektor-ETFs, Schwellen, YouTube-Kanäle, Watchlist (Körbe `wachstum`, `dividende`, optional `kaufzone` je Titel).
- `import_depot.py <export.csv> ...`: liest die Depot-Exporte (Depot 1 mit Kopf `"DATUM","KUNDENNUMMER",...` und finanzen.net zero `Name;ISIN;...`), addiert gleiche ISINs und schreibt `portfolio.csv`. Kunden-/Depotnummern werden nicht übernommen. ISIN→Ticker steht in `isin_map.yaml` (von Hand korrigiert: GOOGL, VAR.OL, BNTX, SONY).
- `monitor.py`: holt Kurse (yfinance), bewertet das Portfolio in EUR, prüft Schwellen, schreibt `reports/JJJJ-MM-TT_HHMM.md` und `reports/latest.json`. Hinweise haben zwei Stufen: `neu_wichtig` (für Push) und `neu_weitere` (nur Bericht). `state.json` merkt sich aktive Hinweise, damit nur neue gemeldet werden.
- `import_listen.py`: liest `quellen/google-finance-listen.html` (Google-Finance-Seite per Strg+S gespeichert; Listen Beobachtungsliste, BLOCH LIVE, Golden Eye, PAYOFF, medizin) und die aktienlust-Abstauberlisten `quellen/Abstauberliste-*.pdf` (Kauflimit 1/2, Ziel in EUR, Stand April 2025) und schreibt `watchlisten.yaml`. Google-Symbole → Ticker in `google_map.yaml`. Zum Aktualisieren neue Dateien in `quellen/` ablegen und das Skript erneut starten.
  - Abstauber-Limits werden im Monitor um Splits seit Erscheinen bereinigt (Booking 25:1, Netflix 10:1, ServiceNow 5:1, Air Liquide Gratisaktien). Electronic Arts ist seit 08/2026 delistet.
  - Titel, die nur auf externen Listen stehen, melden nur Tagesverluste ab 10 % (wichtig) und Rücksetzer ab 25 % (Bericht), damit es bei rund 300 Titeln ruhig bleibt.
- `monitor.py --schnell`: nur Indizes, VIX und Crash-Muster, ca. 2 Sekunden; für Läufe alle 10–15 Minuten während der Handelszeiten. Lässt die Hinweise des letzten vollen Laufs in `state.json` stehen.
- `crash.py`: Crash-Muster-Score 0–100 (Nasdaq-100-Verlust 5 Tage, VIX-Niveau, VIX-Sprung, Abstand zum Hoch), Stufen Ruhe/Nervosität/Korrektur/Panik. Geeicht: Aug. 2024 = 75, April 2025 (Rosengarten) = 100, März 2026 = 55. Zusätzlich "schleichende Korrektur" (Index ≥ 10 % unter Hoch und ≤ 3 % über 200T, VIX egal) = mindestens Korrektur; erkennt Okt. 2023, Sep. 2024, Juli 2026. Ab Korrektur wichtig. Erholungssignal (VIX −25 % von der Spitze, Index +3 % über Tief) hätte am 11.04.2025 und 08.04.2026 angeschlagen; einmal pro 45 Tage.
- `fear_greed.py`: CNN Fear & Greed Index (Historie ab 2022, Cache in `reports/fear_greed.json`). Monitor meldet wichtig bei ≤ 25, ≤ 15, ≤ 10, je Phase jede Stufe einmal, neue Phase ab ≥ 45 (`fear_greed_reset`); ≥ 80 nur Bericht. Läuft auch im Schnellmodus. Rückblick: unter 10 (Mai 2022, April 2025, Nov. 2025, März 2026) war der Nasdaq 100 drei Monate später +4 bis +34 %; unter 25 allein im Bärenmarkt 2022 mehrfach zu früh. Nutzer hat nach eigener Aussage immer bei sehr niedrigem Wert gekauft.
- `dashboard.py` + `dashboard_vorlage.html`: jeder volle Lauf schreibt `dashboard.html` (eine Datei, Daten eingebettet). Ansehen über den Preview-Server `aktien-dashboard` (Port 8801, nur 127.0.0.1) oder per Doppelklick.
- 90- und 200-Tage-Linie: Unterschreiten der 200T ist bei Kern-Watchlist und Positionen ab 3 % Depotanteil wichtig, alles andere (90T, Annäherung) nur Bericht.
- `ausschluss` in `config.yaml`: Ticker raus aus Watchlist und Listen (aktuell Stellantis, Trade Desk).
- `youtube.py`: neue Videos der Kanäle per RSS, Transkript nach `transkripte/`. Kopfzeile `- Ausgewertet: nein` setzt der Recherche-Agent nach der Auswertung auf `ja`.
- Aufruf jeweils `.venv/Scripts/python <skript>.py` (bei Umlauten in der Konsole `PYTHONIOENCODING=utf-8` setzen).

## Recherche-Agent

- Skill `.claude/skills/recherche/SKILL.md`: Ablauf eines Recherche-Laufs (Daten holen, Transkripte auswerten, Rücksetzer prüfen, neue Ideen, Bericht nach `recherche/`, kurze Telegram-Nachricht nur bei Relevantem).
- `screener.py` → `reports/screener.json`: ≥ 10 Mrd. $, ≥ 15 % unter Hoch, profitabel, nur Heimatbörsen USA/Europa (Kriterien in `config.yaml` → `screener`).
- `anleitung_transkripte.md`: Format der Transkript-Auswertung (eine JSON-Datei je Gruppe in `auswertung/`).
- `erwaehnungen.py` → `erwaehnungen.json` (alle Videos) und `reports/erwaehnungen_uebersicht.json` (je Ticker, letzte 30 Tage); markiert Transkripte als ausgewertet.
- `reports/daten.json`: kompakte Monitor-Daten für den Agenten (schreibt `dashboard.py`).
- Automatisch (Büro-PC, Aufgabenplanung), z. B. 1× täglich nach US-Börsenstart:
  `claude -p "Führe einen Recherche-Lauf nach dem Skill recherche aus." --permission-mode acceptEdits` im Ordner `Aktienresearch`; Websuche und Bash-Befehle müssen dafür in `.claude/settings.json` freigegeben sein.
- Erster Lauf: `recherche/2026-10-08_2215.md`.
- `erholung.py` → `reports/erholung.md/json`: (A) je Stressphase des Crash-Musters, wie tief jede Aktie fiel und nach wie vielen Tagen sie ihr altes Hoch zurück hatte, plus Rangliste "wiederholt schneller als Nasdaq 100"; (B) Abstauberlisten seit Erscheinen 15.04.2025 in EUR vs. Nasdaq 100/DAX und Kursziel. Wöchentlich laufen lassen.
- Split-Erkennung bei Abstauber-Limits: Yahoo-Aktionen und zusätzlich Listenkurs vs. bereinigter Kurs am Erscheinungstag (CrowdStrike 4:1 im Juli 2026 fehlte in den Yahoo-Aktionen).

## Benachrichtigungen

Der Nutzer will wenige Nachrichten, nur bei Wichtigem. Wichtig ist: Index nähert sich der 200-Tage-Linie oder fällt darunter, starker Index-Tagesverlust, Index-Drawdown-Stufen, VIX ab 30, Kaufzone erreicht, Aktie −10 % an einem Tag, Position ab 3 % Depotanteil −6 % an einem Tag. Alles andere landet nur im Bericht.

## Quellen

- YouTube: Wir lieben Aktien, aktienlust, ALWAYS AHEAD, Tim Schäfer, InvestIngenieur, Divizend (seit 11.10.2026), Beating Beta (seit 12.10.2026).
- YouTube-Namenssuche (`youtube_suche` in config.yaml): Thomas Rappold auf allen Kanälen (WELT, Börse Online, Beating Beta, Börsenradio, Divizend "Crunch Time"). Treffer nur, wenn "Rappold" in Titel oder Beschreibung steht.
- Brookfield (12.10.2026): Brookfield Corporation (BN, Holding, Rappold-Idee) in `beobachtung`, Brookfield Infrastructure (BIP, ca. 4,9 % Dividende) in `dividende`.
- Hermès (RMS.PA) in Watchlist-Gruppe `beobachtung` mit Kaufzone 1.250 € (Wunsch 11.10.2026).
- payOFF „The Week“ mit François Bloch (montags) erscheint als Video auf ALWAYS AHEAD und als Artikel unter payoff.ch/news/the-week-…; über den YouTube-Kanal abgedeckt.

## Technische Eigenheiten

- TLS-Inspektion auf diesem Rechner: yfinance nutzt `curl_cffi`, dort hilft `truststore` nicht. `monitor.py` baut deshalb bei jedem Lauf `ca-bundle.pem` aus certifi plus Windows-Zertifikatsspeicher und übergibt es der Session.
- yfinance liefert `dividendYield` und `fiveYearAvgDividendYield` bereits in Prozent.
- Londoner Titel (.L) notieren in Pence (GBp).

## Betrieb

**Aktuell (seit 20.10.2026): Windows-Aufgabenplanung auf dem Laptop ist der Läufer**, Ordner `\Aktienresearch\`: "Aktienresearch schnell" (Mo–Fr 8:00–22:45 alle 15 Min.), "Aktienresearch voll" (Mo–Fr 8:30/15:45/22:30), "Aktienresearch youtube" (täglich 7:00). Startdateien `lauf_*.cmd` (setzen `AKTIEN_LAEUFER=1`), Logs in `logs/`. Unsichtbar über `conhost.exe --headless`, verpasste Läufe werden nachgeholt (StartWhenAvailable). **Sobald GitHub Actions läuft, diese drei Aufgaben deaktivieren**, sonst kommen Meldungen doppelt.

### Geplant: GitHub Actions

- **Monitor läuft in GitHub Actions** (`.github/workflows/monitor.yml`, privates Repo): Schnellprüfung Mo–Fr alle 15 Min. 8:00–22:45 Uhr (Sommerzeit), volle Läufe 8:30/15:45/22:30. Einziger "Läufer" (`AKTIEN_LAEUFER=1`): nur er sendet Telegram und schreibt `state.json`, `kurs_cache.json`, `dashboard.html`, `reports/daten.json`, `reports/latest*.json`, `reports/fear_greed.json`, `reports/20*.md` und committet sie. Telegram-Token/Chat-ID als GitHub-Secrets.
- **Laptop (Hauptrechner) und Büro-PC**: `git pull` für den aktuellen Stand; YouTube, Transkript-Auswertung, Screener, Erholung, Recherche-Berichte, Config-Änderungen lokal, danach commit + push. Lokale Monitor-Läufe schreiben nur `state_lokal.json`, `reports_lokal/`, `dashboard_lokal.html` (gitignored) und senden nie Telegram.
- GitHub-Freiminuten (privat, 2.000/Monat): geschätzt ca. 1.400 bei 15-Minuten-Takt.

## Offen

- **Zwei Rechner (später, Stand 12.10.2026):** Büro-PC = einziger Läufer (Zeitplan, Telegram, state.json), Laptop zu Hause = schauen/steuern. Sync über Cloud-Ordner (Dienst noch offen: OneDrive/Google Drive/Dropbox). Geplant: .venv aus dem Sync-Ordner nehmen, lokale Rollen-Datei (Läufer ja/nein, nicht synchronisiert; ohne Läufer-Rolle kein --telegram und kein Schreiben von state.json), Sperrdatei während eines Laufs. Offen ist auch, welche "lokale KI" im Büro läuft (Claude Code oder lokales Modell).
  - Büro-PC läuft nicht 24/7. Optionen für lückenlose Meldungen: (1) Laptop als Vertretung über Lebenszeichen-Datei im Cloud-Ordner, (2) Monitor (reines Python, keine KI) in der Cloud, z. B. GitHub Actions mit privatem Repo und Token als Secret, (3) Raspberry Pi/NAS zu Hause. Empfehlung: (2) oder (3) für den Monitor, KI-Recherche bleibt lokal. Verpasste Läufe holt die Aufgabenplanung beim Einschalten nach.

- Telegram-Bot (richtet der Nutzer ein) und Zeitplan (Hermes, n8n oder lokal).
- Recherche-Agent: Transkripte auswerten (genannte Aktien, Thesen, Abgleich mit Portfolio/Watchlist), Screener (≥ 10 Mrd. $), Ideen aus Sektorrotation, Rücksetzer prüfen (Grund des Kursrückgangs, These intakt?). Die Bewertungsraster aus dem Community-Paket `trading-skills` (Watchlist-Score, Fundamental-Score) können als Vorlage dienen; das Paket selbst hat keine Datenquelle.
