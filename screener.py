"""Screener für neue Ideen: große, profitable Unternehmen mit deutlichem Rücksetzer.

Passt zur Strategie "Qualität kaufen, wenn sie fällt". Filter (config.yaml, Abschnitt screener):
- Marktkapitalisierung mindestens X Mrd. USD (umgerechnet)
- mindestens Y % unter dem 52-Wochen-Hoch
- positives Ergebnis (KGV > 0)
- nur Heimatbörsen in USA und Europa, keine Doppel-Notierungen

Schreibt reports/screener.json; die inhaltliche Prüfung macht der Recherche-Agent.

Aufruf:  .venv/Scripts/python screener.py
"""

import json
import re
from datetime import datetime
from pathlib import Path

import yaml
import yfinance as yf
from yfinance import EquityQuery as Q

from monitor import session

BASIS = Path(__file__).parent
ZIEL = BASIS / "reports" / "screener.json"

# Yahoo-Börsenkürzel: USA (Nasdaq, NYSE) und europäische Heimatbörsen
BOERSEN = ["NMS", "NYQ", "NGM", "NCM", "ASE", "GER", "LSE", "PAR", "AMS", "EBS", "CPH", "OSL", "STO", "MIL", "MCE", "BRU", "HEL", "VIE"]


def main():
    cfg = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))
    sc = cfg.get("screener", {})
    min_mrd = sc.get("min_marktkap_mrd_usd", 10)
    min_rueck = sc.get("min_ruecksetzer_prozent", 15)
    s = session()

    abfrage = Q("and", [
        Q("is-in", ["exchange", *BOERSEN]),
        Q("gte", ["intradaymarketcap", min_mrd * 1e9 * 0.5]),  # grob vorfiltern, genau wird unten in USD gerechnet
        Q("lt", ["fiftytwowkpercentchange", 50]),
    ])
    treffer, offset = [], 0
    while True:
        antwort = yf.screen(abfrage, size=250, offset=offset, sortField="intradaymarketcap", sortAsc=False, session=s)
        quotes = antwort.get("quotes", [])
        treffer += quotes
        offset += len(quotes)
        if not quotes or offset >= antwort.get("total", 0) or offset >= 2000:
            break

    # Devisenkurse für die Umrechnung in USD
    waehrungen = {q.get("currency") for q in treffer} - {None, "USD"}
    basis = {"GBp": "GBP"}
    fx_sym = {w: f"{basis.get(w, w)}USD=X" for w in waehrungen}
    fx_kurse = yf.download(sorted(set(fx_sym.values())), period="5d", progress=False, session=s)["Close"].ffill().iloc[-1]

    def in_usd(betrag, waehrung):
        if betrag is None:
            return None
        if waehrung in (None, "USD"):
            return betrag
        rate = fx_kurse.get(fx_sym[waehrung])
        return betrag * rate if rate == rate else None  # rate == rate: nicht NaN

    portfolio = set()
    if (BASIS / "portfolio.csv").exists():
        portfolio = {z.split(";")[1] for z in (BASIS / "portfolio.csv").read_text(encoding="utf-8").splitlines()[1:] if z}
    listen = yaml.safe_load((BASIS / "watchlisten.yaml").read_text(encoding="utf-8")) if (BASIS / "watchlisten.yaml").exists() else {}
    bekannt = {t for k, l in listen.items() if k != "_waehrungen" for t in l["titel"]}
    bekannt |= {t for g in cfg["watchlist"].values() for t in g}
    ausschluss = set(cfg.get("ausschluss") or [])

    def rang(q):
        """Heimatbörse zuerst; Zweitlinien (Wien, Mailand '1…', London '0…') ganz raus."""
        sym, ex = q["symbol"], q.get("exchange")
        if ex == "VIE" or (ex == "MIL" and sym[0].isdigit()) or (ex == "LSE" and sym[0].isdigit()):
            return None
        if ex in ("NMS", "NYQ", "NGM", "NCM", "ASE"):
            return 0
        return 2 if ex == "GER" else 1

    def namensschluessel(name):
        woerter = [w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if w not in ("the", "ag", "se", "plc", "inc", "nv", "sa")]
        return " ".join(woerter[:2])

    beste = {}
    for q in treffer:
        r = rang(q)
        if r is None:
            continue
        schl = namensschluessel(q.get("longName") or q.get("shortName") or q["symbol"])
        if schl not in beste or r < beste[schl][0]:
            beste[schl] = (r, q)

    ergebnis = []
    for _, q in beste.values():
        name = q.get("longName") or q.get("shortName") or q["symbol"]
        mcap = in_usd(q.get("marketCap"), q.get("currency"))
        rueck = q.get("fiftyTwoWeekHighChangePercent")
        pe = q.get("trailingPE") or q.get("forwardPE")
        if not mcap or mcap < min_mrd * 1e9 or rueck is None or rueck * 100 > -min_rueck or not pe or pe <= 0:
            continue
        if q["symbol"] in ausschluss:
            continue
        ergebnis.append({
            "ticker": q["symbol"], "name": name, "boerse": q.get("fullExchangeName"),
            "marktkap_mrd_usd": round(mcap / 1e9, 1),
            "unter_hoch_prozent": round(rueck * 100, 1),
            "abstand_200t_prozent": round((q.get("twoHundredDayAverageChangePercent") or 0) * 100, 1),
            "kgv": round(pe, 1),
            "div_rendite": q.get("dividendYield"),
            "im_depot": q["symbol"] in portfolio,
            "auf_liste": q["symbol"] in bekannt,
        })
    ergebnis.sort(key=lambda e: e["unter_hoch_prozent"])
    ZIEL.parent.mkdir(exist_ok=True)
    ZIEL.write_text(json.dumps({"zeit": datetime.now().isoformat(timespec="minutes"),
                                "kriterien": {"min_marktkap_mrd_usd": min_mrd, "min_ruecksetzer_prozent": min_rueck},
                                "titel": ergebnis}, indent=1, ensure_ascii=False), encoding="utf-8")
    neu = [e for e in ergebnis if not e["im_depot"] and not e["auf_liste"]]
    print(f"{len(treffer)} Titel geprüft, {len(ergebnis)} Treffer, davon {len(neu)} weder im Depot noch auf einer Liste -> {ZIEL}")


if __name__ == "__main__":
    main()
