"""Auswertungen der Transkripte sammeln und je Aktie verdichten.

Liest alle auswertung/*.json (Format siehe anleitung_transkripte.md), führt sie in
erwaehnungen.json zusammen (je Video nur einmal), prüft die Ticker gegen Yahoo,
markiert die Transkripte als ausgewertet und schreibt reports/erwaehnungen_uebersicht.json:
je Ticker Anzahl Erwähnungen, Kanäle, Tendenzen und letzte These der letzten 30 Tage.

Aufruf:  .venv/Scripts/python erwaehnungen.py
"""

import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import yfinance as yf

from monitor import session

BASIS = Path(__file__).parent
EINGANG = BASIS / "auswertung"
SAMMLUNG = BASIS / "erwaehnungen.json"
UEBERSICHT = BASIS / "reports" / "erwaehnungen_uebersicht.json"
TRANSKRIPTE = BASIS / "transkripte"
FENSTER_TAGE = 30


def main():
    videos = {v["datei"]: v for v in json.loads(SAMMLUNG.read_text(encoding="utf-8"))} if SAMMLUNG.exists() else {}
    for datei in sorted(EINGANG.glob("*.json")):
        for v in json.loads(datei.read_text(encoding="utf-8")):
            videos[v["datei"]] = v

    # Ticker prüfen: gibt es Kursdaten bei Yahoo?
    ticker = sorted({e["ticker"] for v in videos.values() for e in v.get("erwaehnungen", []) if e.get("ticker")})
    s = session()
    kurse = yf.download(ticker, period="5d", progress=False, session=s)["Close"] if ticker else None
    gueltig = {t for t in ticker if kurse is not None and t in kurse and kurse[t].notna().any()}
    for v in videos.values():
        for e in v.get("erwaehnungen", []):
            e["ticker_ok"] = e.get("ticker") in gueltig

    SAMMLUNG.write_text(json.dumps(sorted(videos.values(), key=lambda v: (v["datum"], v["datei"])), ensure_ascii=False, indent=1), encoding="utf-8")

    # Transkripte als ausgewertet markieren
    for name in videos:
        pfad = TRANSKRIPTE / name
        if pfad.exists():
            text = pfad.read_text(encoding="utf-8")
            if "- Ausgewertet: nein" in text:
                pfad.write_text(text.replace("- Ausgewertet: nein", "- Ausgewertet: ja", 1), encoding="utf-8")

    # Verdichten je Ticker (bzw. Name, wenn kein gültiger Ticker)
    grenze = (date.today() - timedelta(days=FENSTER_TAGE)).isoformat()
    je = defaultdict(list)
    for v in videos.values():
        if v["datum"] < grenze:
            continue
        for e in v.get("erwaehnungen", []):
            schluessel = e["ticker"] if e.get("ticker_ok") else f"? {e['name']}"
            je[schluessel].append({**e, "kanal": v["kanal"], "datum": v["datum"], "titel": v["titel"], "datei": v["datei"]})

    uebersicht = []
    for schluessel, liste in je.items():
        liste.sort(key=lambda e: e["datum"], reverse=True)
        uebersicht.append({
            "ticker": None if schluessel.startswith("? ") else schluessel,
            "name": liste[0]["name"],
            "anzahl": len(liste),
            "kanaele": sorted({e["kanal"] for e in liste}),
            "hauptthema": sum(e.get("gewicht") == "Hauptthema" for e in liste),
            "tendenzen": dict(Counter(e["tendenz"] for e in liste)),
            "letzte": [{k: e.get(k) for k in ("datum", "kanal", "tendenz", "these", "kaufzone_oder_ziel", "titel")} for e in liste[:4]],
        })
    uebersicht.sort(key=lambda u: (len(u["kanaele"]), u["hauptthema"], u["anzahl"]), reverse=True)
    UEBERSICHT.parent.mkdir(exist_ok=True)
    UEBERSICHT.write_text(json.dumps({"fenster_tage": FENSTER_TAGE, "videos": len(videos), "titel": uebersicht},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    ohne = [u["name"] for u in uebersicht if not u["ticker"]]
    print(f"{len(videos)} Videos, {sum(u['anzahl'] for u in uebersicht)} Erwähnungen zu {len(uebersicht)} Titeln. Ohne gültigen Ticker: {', '.join(ohne) or 'keine'}")


if __name__ == "__main__":
    main()
