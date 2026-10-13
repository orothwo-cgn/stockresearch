"""Externe Watchlisten einlesen und nach watchlisten.yaml schreiben.

Quellen (in quellen/):
- google-finance-listen.html: gespeicherte Google-Finance-Seite (Strg+S). Alle Listen
  (Beobachtungsliste, BLOCH LIVE, ...) stehen darin; Indizes und Futures werden übersprungen.
- Abstauberliste-*.pdf (aktienlust): je Aktie ISIN, Kauflimit 1 und 2 sowie Kursziel in Euro.

Ticker-Zuordnungen landen in isin_map.yaml (ISIN) bzw. google_map.yaml (Google-Symbol)
und können dort korrigiert werden. Ein erneuter Lauf übernimmt die Korrekturen.

Aufruf:  .venv/Scripts/python import_listen.py
"""

import html
import re
from pathlib import Path

import pymupdf
import yaml

from import_depot import ISIN_MAP, suche_ticker, waehrung
from monitor import session

BASIS = Path(__file__).parent
QUELLEN = BASIS / "quellen"
GOOGLE_HTML = QUELLEN / "google-finance-listen.html"
GOOGLE_MAP = BASIS / "google_map.yaml"
ZIEL = BASIS / "watchlisten.yaml"

# Google-Börsenkürzel -> Yahoo-Endung; None = über den Namen suchen (deutsche Zweitlistings)
BOERSEN = {
    "NASDAQ": "", "NYSE": "", "NYSEAMERICAN": "", "NYSEARCA": "",
    "LON": ".L", "EPA": ".PA", "EBR": ".BR", "AMS": ".AS", "BME": ".MC", "BIT": ".MI",
    "SWX": ".SW", "ASX": ".AX", "TYO": ".T", "HKG": ".HK", "CVE": ".V", "TSE": ".TO",
    "SGX": ".SI", "BVMF": ".SA", "VIE": ".VI", "OSL": ".OL", "CPH": ".CO", "STO": ".ST",
    "ETR": None, "FRA": None, "BMV": None, "MEHRDEUTIG": None,
}
GOOGLE_LISTEN = ["Beobachtungsliste", "BLOCH LIVE", "Golden Eye", "PAYOFF", "medizin", "Aktiensektoren"]


def lade(pfad):
    return (yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}) if pfad.exists() else {}


def zahl(text):
    return float(text.strip().rstrip("%").replace(".", "").replace(",", "."))


def lies_abstauber(pdf):
    teile = [t.strip() for t in "".join(seite.get_text() for seite in pymupdf.open(pdf)).splitlines() if t.strip()]
    for i, t in enumerate(teile):
        if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", t):
            werte = teile[i + 1:i + 11]
            try:
                kurs, hoch, tief, _, limit1, limit2, ziel = (zahl(w) for w in werte[:7])
            except ValueError:
                continue
            yield {"isin": t, "name": teile[i - 1], "kurs_eur": kurs, "limit1_eur": limit1, "limit2_eur": limit2, "ziel_eur": ziel}


def lies_google(pfad):
    h = pfad.read_text(encoding="utf-8", errors="replace")
    boersen = {}
    for sym, b in re.findall(r"quote/([A-Za-z0-9.\-]+):([A-Z]+)", h):
        boersen.setdefault(sym, set()).add(b)
    # Gleiches Kürzel an mehreren Börsen (GIS = Gilead in Frankfurt, General Mills in NY): über den Namen auflösen
    boerse = {sym: (bs.pop() if len(bs) == 1 else "MEHRDEUTIG") for sym, bs in boersen.items()}
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    zeilen = [z.strip() for z in html.unescape(re.sub(r"<[^>]+>", "\n", text)).split("\n") if z.strip()]
    # Überschrift jeder Liste: letztes Vorkommen des Namens (das erste ist das Auswahlmenü)
    start = {n: max(i for i, z in enumerate(zeilen) if z == n) for n in GOOGLE_LISTEN}
    start["Beobachtungsliste"] = next(i for i, z in enumerate(zeilen) if z.startswith("Diese Liste enth"))
    grenzen = sorted((pos, n) for n, pos in start.items())
    listen = {n: [] for n in GOOGLE_LISTEN}
    for i in range(len(zeilen) - 5):
        a = zeilen[i:i + 5]
        if a[0] == a[2] == a[4] and a[1] == a[3] and a[0] != a[1] and " " not in a[0] and len(a[0]) <= 14:
            liste = [n for pos, n in grenzen if pos < i][-1]
            listen[liste].append((a[0], boerse.get(a[0], ""), a[1]))
    return listen


def main():
    s = session()
    isin_karte = lade(ISIN_MAP)
    google_karte = lade(GOOGLE_MAP)
    ergebnis = {}

    for pdf in sorted(QUELLEN.glob("Abstauberliste-*.pdf")):
        schluessel = "abstauber_" + ("usa" if "USA" in pdf.name else "europa")
        titel = {}
        for z in lies_abstauber(pdf):
            if z["isin"] not in isin_karte:
                isin_karte[z["isin"]] = {"ticker": suche_ticker(z["isin"], s), "name": z["name"]}
            eintrag = isin_karte[z["isin"]]
            if not eintrag.get("ticker"):
                print(f"  ohne Ticker: {z['name']} ({z['isin']})")
                continue
            titel[eintrag["ticker"]] = {"name": z["name"], "isin": z["isin"], "kurs_eur": z["kurs_eur"], "limit1_eur": z["limit1_eur"],
                                        "limit2_eur": z["limit2_eur"], "ziel_eur": z["ziel_eur"]}
        # Stand der Limits: beide Listen erschienen im April 2025 (Zoll-Korrektur); für die Split-Bereinigung
        ergebnis[schluessel] = {"quelle": f"aktienlust, {pdf.name}", "stand": "2025-04-15", "titel": titel}
        print(f"{schluessel}: {len(titel)} Titel")

    if GOOGLE_HTML.exists():
        for liste, eintraege in lies_google(GOOGLE_HTML).items():
            titel = {}
            for symbol, boerse, name in eintraege:
                if boerse.startswith("INDEX") or boerse in ("CME", "NYMEX", "COMEX", "CBOT", "SHA", ""):
                    continue
                schl = f"{symbol}:{boerse}"
                if schl not in google_karte:
                    endung = BOERSEN.get(boerse)
                    if endung is None:
                        ticker = suche_ticker(name, s)
                    else:
                        ticker = (symbol.zfill(4) if boerse == "HKG" else symbol.replace(".", "-")) + endung
                    google_karte[schl] = {"ticker": ticker, "name": name}
                    print(f"  {schl} {name}: {ticker or 'NICHT GEFUNDEN'}")
                ticker = google_karte[schl].get("ticker")
                if ticker:
                    titel.setdefault(ticker, {"name": name})
            ergebnis["google_" + re.sub(r"\W+", "_", liste.lower()).strip("_")] = {"quelle": f"Google Finance, Liste {liste}", "titel": titel}
            print(f"Google {liste}: {len(titel)} Titel")

    # Handelswährung je Ticker (Abstauber-Limits sind in Euro)
    waehrungen = lade(ZIEL).get("_waehrungen", {})
    for liste in ergebnis.values():
        for ticker in liste["titel"]:
            if ticker not in waehrungen:
                waehrungen[ticker] = waehrung(ticker, s)
    ergebnis["_waehrungen"] = waehrungen

    for pfad, karte, kopf in [(ISIN_MAP, isin_karte, "ISIN -> Yahoo-Ticker"), (GOOGLE_MAP, google_karte, "Google-Symbol -> Yahoo-Ticker")]:
        pfad.write_text(f"# {kopf}. Ticker korrigieren oder leeren, wenn die Zuordnung falsch ist.\n"
                        + yaml.safe_dump(karte, allow_unicode=True, sort_keys=True), encoding="utf-8")
    ZIEL.write_text("# Erzeugt von import_listen.py, nicht von Hand bearbeiten.\n"
                    + yaml.safe_dump(ergebnis, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ohne = [t for t, w in waehrungen.items() if not w]
    print(f"{ZIEL.name} geschrieben. Ohne Kursdaten bei Yahoo: {', '.join(ohne) or 'keine'}")


if __name__ == "__main__":
    main()
