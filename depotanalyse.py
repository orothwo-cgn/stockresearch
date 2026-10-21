"""Depotanalyse: Gewichtung, Klumpenrisiko, Sektoren, Länder, Währungen, Korrelation, Dividenden.

Grundlage: portfolio.csv (Stückzahlen), Kurse und Stammdaten von Yahoo Finance.
Stammdaten (Sektor, Land, Dividende) werden in reports/stammdaten.json zwischengespeichert
(7 Tage gültig), damit Folgeläufe schnell sind.

Schreibt reports/depotanalyse.md und reports/depotanalyse.json.

Aufruf:  .venv/Scripts/python depotanalyse.py
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from monitor import fmt, lade_portfolio, session

BASIS = Path(__file__).parent
STAMM = BASIS / "reports" / "stammdaten.json"
ZIEL_MD = BASIS / "reports" / "depotanalyse.md"
ZIEL_JSON = BASIS / "reports" / "depotanalyse.json"
SEKTOR_DE = {
    "Technology": "Technologie", "Healthcare": "Gesundheit", "Financial Services": "Finanzen",
    "Consumer Cyclical": "Zykl. Konsum", "Consumer Defensive": "Basiskonsum", "Communication Services": "Kommunikation",
    "Industrials": "Industrie", "Energy": "Energie", "Basic Materials": "Grundstoffe", "Utilities": "Versorger",
    "Real Estate": "Immobilien",
}


def stammdaten(ticker_liste, s):
    cache = json.loads(STAMM.read_text(encoding="utf-8")) if STAMM.exists() else {}
    grenze = (datetime.now() - timedelta(days=7)).isoformat()
    for t in ticker_liste:
        if t in cache and cache[t].get("stand", "") > grenze:
            continue
        try:
            i = yf.Ticker(t, session=s).info
        except Exception:
            i = {}
        cache[t] = {"sektor": i.get("sector"), "branche": i.get("industry"), "land": i.get("country"),
                    "dividende": i.get("dividendYield"), "name": i.get("shortName"), "beta": i.get("beta"),
                    "stand": datetime.now().isoformat(timespec="minutes")}
    STAMM.parent.mkdir(exist_ok=True)
    STAMM.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache


def main():
    s = session()
    portfolio = lade_portfolio()
    ticker = list(portfolio)
    waehrungen = {p["waehrung"] for p in portfolio.values() if p["waehrung"]}
    basis = {"GBp": "GBP"}
    fx = sorted({f"EUR{basis.get(w, w)}=X" for w in waehrungen if basis.get(w, w) != "EUR"})
    kurse = yf.download(ticker + fx + ["^NDX", "^GSPC"], period="1y", auto_adjust=True, progress=False, session=s)["Close"].ffill()
    letzte = kurse.iloc[-1]

    def in_eur(betrag, w):
        if w == "EUR":
            return betrag
        teiler = 100 if w == "GBp" else 1
        return betrag / teiler / letzte[f"EUR{basis.get(w, w)}=X"]

    zeilen = []
    for t, p in portfolio.items():
        if t not in letzte or pd.isna(letzte[t]) or not p["waehrung"]:
            continue
        zeilen.append({"ticker": t, "name": p["name"], "waehrung": p["waehrung"], "wert": in_eur(letzte[t] * p["stueck"], p["waehrung"])})
    df = pd.DataFrame(zeilen).set_index("ticker")
    gesamt = df["wert"].sum()
    df["gewicht"] = df["wert"] / gesamt * 100
    df = df.sort_values("gewicht", ascending=False)

    st = stammdaten(list(df.index), s)
    df["sektor"] = [SEKTOR_DE.get(st[t]["sektor"], st[t]["sektor"] or "unbekannt") for t in df.index]
    df["land"] = [st[t]["land"] or "unbekannt" for t in df.index]
    df["dividende"] = [st[t]["dividende"] or 0.0 for t in df.index]
    df["div_eur"] = df["wert"] * df["dividende"] / 100

    # Klumpenrisiko
    top10 = df["gewicht"].head(10).sum()
    hhi = (df["gewicht"] ** 2).sum()  # Herfindahl-Index: 10.000 = eine Aktie, 100 = 100 gleich große
    effektiv = 10000 / hhi

    sektoren = df.groupby("sektor")["gewicht"].sum().sort_values(ascending=False)
    laender = df.groupby("land")["gewicht"].sum().sort_values(ascending=False)
    waehr = df.groupby("waehrung")["gewicht"].sum().sort_values(ascending=False)

    # Korrelation und Risiko (Tagesrenditen der letzten 12 Monate in Handelswährung)
    renditen = kurse[list(df.index)].pct_change().dropna(how="all")
    gew = df["gewicht"] / 100
    depot_r = (renditen.fillna(0) * gew).sum(axis=1)
    ndx_r = kurse["^NDX"].pct_change().reindex(depot_r.index)
    beta_ndx = depot_r.cov(ndx_r) / ndx_r.var()
    korr_ndx = depot_r.corr(ndx_r)
    vol = depot_r.std() * np.sqrt(252) * 100
    verlauf = (1 + depot_r).cumprod()
    max_dd = ((verlauf / verlauf.cummax()) - 1).min() * 100
    ndx_verlauf = (1 + ndx_r.fillna(0)).cumprod()
    ndx_dd = ((ndx_verlauf / ndx_verlauf.cummax()) - 1).min() * 100

    top = list(df.index[:30])
    korr = renditen[top].corr()
    paare = []
    for i, a in enumerate(top):
        for b in top[i + 1:]:
            if korr.loc[a, b] >= 0.6:
                paare.append((korr.loc[a, b], a, b))
    paare.sort(reverse=True)
    # mittlere Korrelation der Top 30 untereinander
    mittel = korr.where(~np.eye(len(top), dtype=bool)).stack().mean()

    div_zahler = df[df["dividende"] >= 2.0]
    div_summe = df["div_eur"].sum()

    n = lambda t: f"{df.loc[t, 'name'][:28].strip()} ({t})"
    z = [f"# Depotanalyse {datetime.now():%d.%m.%Y}", "",
         f"Depotwert {fmt(gesamt, 0)} € in {len(df)} Positionen. Kurse von Yahoo Finance, umgerechnet in Euro. Keine Anlageberatung.", "",
         "## Kurzfassung", "",
         f"- **Klumpenrisiko:** Die 10 größten Positionen machen {fmt(top10, 1, True)} aus. Rechnerisch entspricht das Depot {fmt(effektiv, 0)} gleich großen Positionen (bei 131 Titeln).",
         f"- **Größte Position:** {n(df.index[0])} mit {fmt(df['gewicht'].iloc[0], 1, True)}.",
         f"- **Sektoren:** " + ", ".join(f"{k} {fmt(v, 0, True)}" for k, v in sektoren.head(4).items()) + ".",
         f"- **Abhängigkeit vom Nasdaq 100:** Beta {fmt(beta_ndx, 2)}, Korrelation {fmt(korr_ndx, 2)}. Steigt oder fällt der Nasdaq 100 um 10 %, bewegte sich das Depot im letzten Jahr im Schnitt um etwa {fmt(beta_ndx * 10, 1, True)}.",
         f"- **Schwankung:** {fmt(vol, 1, True)} pro Jahr; größter Rückgang der heutigen Zusammensetzung in 12 Monaten {fmt(max_dd, 1, True)} (Nasdaq 100: {fmt(ndx_dd, 1, True)}).",
         f"- **Dividenden:** erwartet rund {fmt(div_summe, 0)} € im Jahr ({fmt(div_summe / gesamt * 100, 2, True)} Depotrendite). {len(div_zahler)} Titel mit mindestens 2 % Rendite, zusammen {fmt(div_zahler['gewicht'].sum(), 1, True)} des Depots.", "",
         "## Größte Positionen", "", "| Titel | Gewicht | Wert € | Sektor | Dividende |", "|---|---:|---:|---|---:|"]
    kumuliert = 0
    for t, r in df.head(15).iterrows():
        kumuliert += r["gewicht"]
        z.append(f"| {n(t)} | {fmt(r['gewicht'], 1, True)} | {fmt(r['wert'], 0)} | {r['sektor']} | {fmt(r['dividende'], 2, True) if r['dividende'] else '–'} |")
    z += ["", f"Top 15 zusammen: {fmt(kumuliert, 1, True)}. Positionen unter 0,5 %: {int((df['gewicht'] < 0.5).sum())} Stück, zusammen {fmt(df[df['gewicht'] < 0.5]['gewicht'].sum(), 1, True)}.", "",
          "## Sektoren", "", "| Sektor | Anteil | größte Werte |", "|---|---:|---|"]
    for sek, anteil in sektoren.items():
        groesste = ", ".join(df[df["sektor"] == sek]["name"].head(3).str[:20].str.strip())
        z.append(f"| {sek} | {fmt(anteil, 1, True)} | {groesste} |")
    z += ["", "## Länder und Währungen", "", "| Land | Anteil |", "|---|---:|"] + [f"| {k} | {fmt(v, 1, True)} |" for k, v in laender.head(10).items()]
    z += ["", "| Währung | Anteil |", "|---|---:|"] + [f"| {k} | {fmt(v, 1, True)} |" for k, v in waehr.items()]
    z += ["", "## Korrelation (Top 30 Positionen, 12 Monate)", "",
          f"Mittlere Korrelation untereinander: {fmt(mittel, 2)} (0 = unabhängig, 1 = bewegen sich gleich).", "",
          "Stark gleichlaufende Paare (Korrelation ab 0,6), diese Werte fallen und steigen meist gemeinsam:", ""]
    z += [f"- {n(a)} und {n(b)}: {fmt(k, 2)}" for k, a, b in paare[:15]] or ["- keine"]
    z += ["", "## Dividenden", "", "| Titel | Rendite | Gewicht | Dividende €/Jahr |", "|---|---:|---:|---:|"]
    for t, r in df.sort_values("div_eur", ascending=False).head(15).iterrows():
        z.append(f"| {n(t)} | {fmt(r['dividende'], 2, True)} | {fmt(r['gewicht'], 1, True)} | {fmt(r['div_eur'], 0)} |")
    z += ["", "_Dividendenrenditen laut Yahoo (aktuelle Rendite, Sonderdividenden möglich). Korrelation und Beta aus Tagesrenditen in Handelswährung, ohne Währungseffekte._", ""]
    ZIEL_MD.write_text("\n".join(z), encoding="utf-8")
    ZIEL_JSON.write_text(json.dumps({
        "zeit": datetime.now().isoformat(timespec="minutes"), "wert": gesamt, "positionen": len(df),
        "top10": top10, "effektiv": effektiv, "beta_ndx": beta_ndx, "korr_ndx": korr_ndx, "vol": vol, "max_dd": max_dd,
        "dividende_eur": div_summe, "sektoren": sektoren.to_dict(), "laender": laender.to_dict(), "waehrungen": waehr.to_dict(),
        "paare": [(a, b, k) for k, a, b in paare],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Depotanalyse -> {ZIEL_MD}")


if __name__ == "__main__":
    main()
