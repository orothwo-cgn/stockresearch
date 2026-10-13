"""Depot-Exporte einlesen und zu portfolio.csv zusammenführen.

Unterstützte Formate (werden am Kopf erkannt):
- Export mit Spalten "ISIN", "NAME 1", "STÜCKE", "EINSTANDSWERT", "WÄHRUNG" (Komma, Anführungszeichen)
- finanzen.net zero: "Name;ISIN;...;Anzahl;...;Kaufwert;..." (Semikolon)

Positionen mit gleicher ISIN werden über beide Depots addiert. Die Zuordnung
ISIN -> Yahoo-Ticker steht in isin_map.yaml und kann dort korrigiert werden
(Wert leer lassen = Position wird nicht beobachtet). Kunden- und Depotnummern
werden nicht übernommen.

Aufruf:  .venv/Scripts/python import_depot.py <export1.csv> [<export2.csv> ...]
"""

import csv
import sys
from pathlib import Path

import yaml
import yfinance as yf

from monitor import session

BASIS = Path(__file__).parent
ISIN_MAP = BASIS / "isin_map.yaml"
PORTFOLIO = BASIS / "portfolio.csv"

# Nebenbörsen, die Yahoo bei der ISIN-Suche mit anbietet; die Heimatbörse ist besser
NEBENBOERSEN = (".SG", ".F", ".DU", ".BE", ".MU", ".HM", ".HA")


def suche_ticker(begriff, s):
    """Yahoo-Suche nach ISIN oder Name; erster Aktien-Treffer an der Heimatbörse."""
    try:
        for q in yf.Search(begriff, max_results=8, news_count=0, session=s).quotes:
            sym = q.get("symbol", "")
            if q.get("quoteType") == "EQUITY" and not sym.endswith(NEBENBOERSEN):
                return sym
    except Exception as fehler:
        print(f"  Suche fehlgeschlagen für {begriff}: {fehler}")
    return None


def waehrung(ticker, s):
    try:
        return yf.Ticker(ticker, session=s).fast_info["currency"]
    except Exception:
        return None


def zahl(text):
    text = (text or "").strip()
    return float(text.replace(".", "").replace(",", ".")) if text else None


def lies_export(pfad):
    roh = Path(pfad).read_text(encoding="utf-8-sig")
    kopf = roh.splitlines()[0]
    name = Path(pfad).stem
    if kopf.startswith('"DATUM"'):
        for z in csv.DictReader(roh.splitlines(), delimiter=","):
            stueck = zahl(z["STÜCKE"])
            if stueck:
                yield {"isin": z["ISIN"], "name": z["NAME 1"], "stueck": stueck,
                       "einstand": zahl(z["EINSTANDSWERT"]), "waehrung": z["WÄHRUNG"], "depot": "Depot 1"}
    elif kopf.startswith("Name;ISIN"):
        for z in csv.DictReader(roh.splitlines(), delimiter=";"):
            stueck = zahl(z["Anzahl"])
            if stueck:
                yield {"isin": z["ISIN"], "name": z["Name"], "stueck": stueck,
                       "einstand": zahl(z["Kaufwert"]), "waehrung": "EUR", "depot": "zero"}
    else:
        sys.exit(f"Unbekanntes Format: {name}")


def main(pfade):
    positionen = {}
    for pfad in pfade:
        for p in lies_export(pfad):
            pos = positionen.setdefault(p["isin"], {"name": p["name"], "stueck": 0.0, "einstand": {}, "depots": set()})
            pos["stueck"] += p["stueck"]
            pos["einstand"][p["waehrung"]] = pos["einstand"].get(p["waehrung"], 0.0) + (p["einstand"] or 0.0)
            pos["depots"].add(p["depot"])

    karte = yaml.safe_load(ISIN_MAP.read_text(encoding="utf-8")) if ISIN_MAP.exists() else {}
    karte = karte or {}
    s = session()
    for isin, pos in positionen.items():
        if isin in karte:
            continue
        ticker = suche_ticker(isin, s)
        karte[isin] = {"ticker": ticker, "name": pos["name"]}
        print(f"  {isin} {pos['name']}: {ticker or 'NICHT GEFUNDEN'}")

    # Handelswährung je Ticker (für die Umrechnung in EUR)
    for isin, eintrag in karte.items():
        if eintrag.get("ticker") and not eintrag.get("waehrung"):
            eintrag["waehrung"] = waehrung(eintrag["ticker"], s)

    ISIN_MAP.write_text(
        "# ISIN -> Yahoo-Ticker. Ticker korrigieren oder leeren, wenn die Zuordnung falsch ist.\n"
        + yaml.safe_dump(karte, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )

    with PORTFOLIO.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["isin", "ticker", "name", "stueck", "einstand", "depots"])
        for isin, pos in sorted(positionen.items(), key=lambda kv: kv[1]["name"].lower()):
            # Einstand je Währung getrennt, z. B. "EUR=1200.50|USD=235.85"
            einstand = "|".join(f"{wa}={betrag:.2f}" for wa, betrag in pos["einstand"].items())
            w.writerow([isin, karte[isin].get("ticker") or "", pos["name"], f"{pos['stueck']:g}",
                        einstand, "+".join(sorted(pos["depots"]))])

    ohne = [i for i in positionen if not karte[i].get("ticker")]
    print(f"{len(positionen)} Positionen nach {PORTFOLIO.name} geschrieben, {len(ohne)} ohne Ticker.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
