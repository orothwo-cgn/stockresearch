"""Stammdaten je Titel (Sektor, Branche, Dividende, KGV, Termine) mit Zwischenspeicher.

Für Watchlist-Titel liefert der Monitor ohnehin `info` von Yahoo; die übernehmen wir.
Depot-Titel ohne Watchlist-Eintrag werden höchstens alle `MAX_ALTER_TAGE` Tage neu abgefragt,
pro Lauf höchstens `MAX_ABRUFE` Stück, damit ein Lauf nicht minutenlang hängt.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yfinance as yf

MAX_ALTER_TAGE = 7
MAX_ABRUFE = 45

SEKTOR_DE = {
    "Technology": "Technologie",
    "Communication Services": "Kommunikation",
    "Consumer Cyclical": "Zyklischer Konsum",
    "Consumer Defensive": "Basiskonsum",
    "Financial Services": "Finanzen",
    "Healthcare": "Gesundheit",
    "Industrials": "Industrie",
    "Energy": "Energie",
    "Utilities": "Versorger",
    "Real Estate": "Immobilien",
    "Basic Materials": "Grundstoffe",
}


def _datum(ts):
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d") if ts else None
    except (TypeError, ValueError, OSError):
        return None


def auszug(info):
    """Das, was das Dashboard braucht, aus einem Yahoo-`info`."""
    if not info or info.get("_fehler"):
        return None
    art = info.get("quoteType")
    sektor = info.get("sector")
    if art in ("ETF", "MUTUALFUND"):
        sektor_de = "ETF / Fonds"
    else:
        sektor_de = SEKTOR_DE.get(sektor, sektor) if sektor else None
    zahlen = info.get("earningsTimestampStart") or info.get("earningsTimestamp")
    return {
        "sektor": sektor_de,
        "branche": info.get("industry"),
        "land": info.get("country"),
        "div": info.get("dividendYield"),            # Prozent, z. B. 7.7
        "div5j": info.get("fiveYearAvgDividendYield"),  # Prozent
        "kgv": info.get("trailingPE"),
        "kgv_fwd": info.get("forwardPE"),
        "zahlen": _datum(zahlen),
        "exdiv": _datum(info.get("exDividendDate")),
    }


def lade(ticker_liste, infos, session, pfad: Path):
    """Gibt {ticker: auszug} zurück und schreibt den Zwischenspeicher fort."""
    cache = json.loads(pfad.read_text(encoding="utf-8")) if pfad.exists() else {}
    heute = datetime.now()
    abrufe = 0
    for t in ticker_liste:
        if t in infos:
            a = auszug(infos[t])
            if a:
                cache[t] = {**a, "abgerufen": heute.strftime("%Y-%m-%d")}
            continue
        alt = cache.get(t)
        frisch = alt and datetime.strptime(alt["abgerufen"], "%Y-%m-%d") > heute - timedelta(days=MAX_ALTER_TAGE)
        if frisch or abrufe >= MAX_ABRUFE:
            continue
        abrufe += 1
        try:
            a = auszug(yf.Ticker(t, session=session).info)
        except Exception:  # einzelner Ticker darf den Lauf nicht abbrechen
            a = None
        if a:
            cache[t] = {**a, "abgerufen": heute.strftime("%Y-%m-%d")}
        elif alt:
            cache[t]["abgerufen"] = heute.strftime("%Y-%m-%d")  # nicht bei jedem Lauf erneut versuchen
    pfad.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return {t: cache.get(t) for t in ticker_liste}
