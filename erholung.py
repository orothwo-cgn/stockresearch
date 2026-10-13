"""Erholungsanalyse: Wer kommt nach Crash- und Korrekturphasen am schnellsten zurück?

A) Für jede Stressphase des Crash-Musters (crash.py, ab Stufe Korrektur) je Aktie:
   - Hoch vor der Phase (höchster Schluss der 40 Handelstage davor)
   - Tief in der Phase (bis 20 Handelstage nach ihrem Ende)
   - Tage vom Tief zurück aufs alte Hoch (Kalendertage), sonst "noch nicht"
   Verglichen mit dem Nasdaq 100. Daraus ein Erholungs-Score: in wie vielen Phasen
   war die Aktie schneller zurück als der Index.

B) Abstauberlisten: Entwicklung seit Erscheinen (15.04.2025) in Handelswährung und in
   Euro, verglichen mit Nasdaq 100 und DAX, dazu Stand gegenüber dem Kursziel der Liste.

Schreibt reports/erholung.json und reports/erholung.md.

Aufruf:  .venv/Scripts/python erholung.py
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
import yfinance as yf

import crash
from monitor import lade_portfolio, session

BASIS = Path(__file__).parent
ZIEL_JSON = BASIS / "reports" / "erholung.json"
ZIEL_MD = BASIS / "reports" / "erholung.md"
VORLAUF = 40      # Handelstage vor der Phase für das "alte Hoch"
NACHLAUF = 20     # Handelstage nach Phasenende, in denen das Tief noch liegen darf


def prozent(x):
    return None if x is None or pd.isna(x) else round(float(x) * 100, 1)


def erholung_einer_phase(serie, von, bis):
    s = serie.dropna()
    if len(s) < 100 or s.index[0] > von - pd.Timedelta(days=60):
        return None
    vor = s[s.index < von].iloc[-VORLAUF:]
    if vor.empty:
        return None
    hoch = vor.max()
    nach_ende = s[s.index > bis].iloc[:NACHLAUF]
    fenster = s[(s.index >= vor.index[-1]) & (s.index <= (nach_ende.index[-1] if len(nach_ende) else bis))]
    if fenster.empty:
        return None
    tief_datum = fenster.idxmin()
    tief = fenster.min()
    danach = s[s.index > tief_datum]
    zurueck = danach[danach >= hoch]
    tage = (zurueck.index[0] - tief_datum).days if len(zurueck) else None
    return {"tiefe": prozent(tief / hoch - 1), "tage": tage, "tief_datum": tief_datum.strftime("%Y-%m-%d"),
            "heute_vs_hoch": prozent(s.iloc[-1] / hoch - 1),
            "3m_nach_tief": prozent(s[s.index >= tief_datum].iloc[min(63, len(danach))] / tief - 1) if len(danach) else None}


def main():
    cfg = yaml.safe_load((BASIS / "config.yaml").read_text(encoding="utf-8"))
    listen = yaml.safe_load((BASIS / "watchlisten.yaml").read_text(encoding="utf-8"))
    waehrungen = listen.pop("_waehrungen", {})
    portfolio = lade_portfolio()
    ausschluss = set(cfg.get("ausschluss") or [])

    namen = {}
    for l in listen.values():
        for t, d in l["titel"].items():
            namen.setdefault(t, d["name"])
    for g in cfg["watchlist"].values():
        for t, d in g.items():
            namen[t] = (d or {}).get("name", t)
    for t, p in portfolio.items():
        namen.setdefault(t, p["name"])
    universum = [t for t in namen if t not in ausschluss]
    index, vix, dax = cfg["crash_index"], cfg["vix"], "^GDAXI"

    s = session()
    fx_paare = sorted({f"EUR{'GBP' if w == 'GBp' else w}=X" for w in set(waehrungen.values()) | {p['waehrung'] for p in portfolio.values()} if w and w != "EUR"})
    daten = yf.download(universum + [index, vix, dax] + fx_paare, period="3y", auto_adjust=True, progress=False, session=s)["Close"]

    # A) Phasen
    verlauf = crash.verlauf(daten[index], daten[vix])
    phasen = [p for p in crash.episoden(verlauf) if p["max"] >= 45]
    ergebnis_phasen = []
    score = {t: {"schneller": 0, "phasen": 0, "tage": []} for t in universum}
    for p in phasen:
        von = pd.Timestamp(datetime.strptime(p["von"], "%d.%m.%Y"))
        bis = pd.Timestamp(datetime.strptime(p["bis"], "%d.%m.%Y"))
        idx = erholung_einer_phase(daten[index], von, bis)
        if not idx:
            continue
        titel = []
        for t in universum:
            if t not in daten:
                continue
            r = erholung_einer_phase(daten[t], von, bis)
            if not r or r["tiefe"] is None or r["tiefe"] > -5:  # kaum gefallen: zählt nicht als Erholung
                continue
            titel.append({"ticker": t, "name": namen[t], "im_depot": t in portfolio, **r})
            sc = score[t]
            sc["phasen"] += 1
            if r["tage"] is not None and (idx["tage"] is None or r["tage"] < idx["tage"]):
                sc["schneller"] += 1
            if r["tage"] is not None:
                sc["tage"].append(r["tage"])
        titel.sort(key=lambda x: (x["tage"] is None, x["tage"] if x["tage"] is not None else 0, x["tiefe"]))
        ergebnis_phasen.append({**p, "index": idx, "titel": titel})

    rangliste = []
    for t, sc in score.items():
        if sc["phasen"] >= 2:
            rangliste.append({"ticker": t, "name": namen[t], "im_depot": t in portfolio, "phasen": sc["phasen"],
                              "schneller_als_index": sc["schneller"], "quote": round(sc["schneller"] / sc["phasen"] * 100),
                              "median_tage": int(pd.Series(sc["tage"]).median()) if sc["tage"] else None})
    rangliste.sort(key=lambda r: (-r["quote"], -r["phasen"], r["median_tage"] if r["median_tage"] is not None else 9999))

    # B) Abstauberlisten seit Erscheinen
    def eur_reihe(t):
        w = waehrungen.get(t) or (portfolio.get(t) or {}).get("waehrung")
        reihe = daten[t].dropna()
        if w in (None, "EUR"):
            return reihe
        teiler = 100 if w == "GBp" else 1
        fx = daten.get(f"EUR{'GBP' if w == 'GBp' else w}=X")
        if fx is None:
            return None
        return (reihe / teiler / fx.reindex(reihe.index).ffill()).dropna()

    def seit(reihe, datum):
        reihe = reihe.dropna()
        start = reihe[reihe.index >= pd.Timestamp(datum)]
        return prozent(reihe.iloc[-1] / start.iloc[0] - 1) if len(start) else None

    vergleich = {"Nasdaq 100": seit(daten[index], "2025-04-15"), "DAX": seit(daten[dax], "2025-04-15")}
    abstauber = []
    for schl, l in listen.items():
        if not schl.startswith("abstauber"):
            continue
        for t, d in l["titel"].items():
            if t in ausschluss or t not in daten:
                continue
            reihe_eur = eur_reihe(t)
            if reihe_eur is None or reihe_eur.empty:
                continue
            # Kursziel um Splits seit Erscheinen bereinigen: Verhältnis Liste-Kurs zu bereinigtem Startkurs
            start = reihe_eur[reihe_eur.index >= pd.Timestamp(l["stand"])]
            faktor = d["kurs_eur"] / start.iloc[0] if d.get("kurs_eur") and len(start) else 1.0
            ziel = d["ziel_eur"] / faktor if faktor > 1.5 else d["ziel_eur"]  # nur bei echtem Split umrechnen
            abstauber.append({"ticker": t, "name": d["name"], "liste": "USA" if schl.endswith("usa") else "Europa",
                              "im_depot": t in portfolio,
                              "seit_liste_eur": seit(reihe_eur, l["stand"]),
                              "seit_liste_lokal": seit(daten[t], l["stand"]),
                              "kurs_eur": round(float(reihe_eur.iloc[-1]), 2), "ziel_eur": round(ziel, 2),
                              "zum_ziel": prozent(ziel / reihe_eur.iloc[-1] - 1)})
    abstauber.sort(key=lambda a: -(a["seit_liste_eur"] or -999))

    ZIEL_JSON.write_text(json.dumps({"zeit": datetime.now().isoformat(timespec="minutes"), "phasen": ergebnis_phasen,
                                     "rangliste": rangliste, "abstauber": abstauber, "vergleich_seit_liste": vergleich},
                                    ensure_ascii=False, indent=1), encoding="utf-8")

    # Bericht
    f = lambda v, vz=True: "–" if v is None else (f"+{v:.1f}".replace(".", ",") if vz and v > 0 else f"{v:.1f}".replace(".", ",")) + " %"
    z = [f"# Erholungsanalyse {datetime.now():%d.%m.%Y}", "",
         "Wie schnell kamen Aktien nach den Stressphasen des Crash-Musters zurück auf ihr altes Hoch? "
         "Altes Hoch = höchster Schluss der 40 Handelstage vor der Phase. Nur Titel, die mindestens 5 % gefallen sind.", "",
         "## Rangliste: wiederholt schneller zurück als der Nasdaq 100", "",
         "| Titel | im Depot | Phasen | schneller als Index | Median Tage bis altes Hoch |", "|---|:---:|---:|---:|---:|"]
    for r in rangliste[:30]:
        z.append(f"| {r['name']} ({r['ticker']}) | {'ja' if r['im_depot'] else ''} | {r['phasen']} | {r['schneller_als_index']} ({r['quote']} %) | {r['median_tage'] if r['median_tage'] is not None else '–'} |")
    for p in reversed(ergebnis_phasen):
        i = p["index"]
        z += ["", f"## Phase {p['von']} – {p['bis']} ({p['stufe']}, Score {p['max']})", "",
              f"Nasdaq 100: {f(i['tiefe'])} bis zum Tief am {i['tief_datum']}, zurück auf altem Hoch nach "
              f"{str(i['tage']) + ' Tagen' if i['tage'] is not None else '– (noch nicht)'}, drei Monate nach dem Tief {f(i['3m_nach_tief'])}.", "",
              "| Titel | im Depot | Rückgang | Tage bis altes Hoch | 3 Monate nach Tief | heute vs. altes Hoch |", "|---|:---:|---:|---:|---:|---:|"]
        for x in p["titel"][:15]:
            z.append(f"| {x['name']} ({x['ticker']}) | {'ja' if x['im_depot'] else ''} | {f(x['tiefe'])} | {x['tage'] if x['tage'] is not None else 'noch nicht'} | {f(x['3m_nach_tief'])} | {f(x['heute_vs_hoch'])} |")
    z += ["", "## Abstauberlisten: Entwicklung seit Erscheinen (15.04.2025)", "",
          f"Zum Vergleich: Nasdaq 100 {f(vergleich['Nasdaq 100'])}, DAX {f(vergleich['DAX'])} (Kurs, ohne Dividenden bei Indizes).", "",
          "| Titel | Liste | im Depot | seit Liste (EUR) | Kurs € | Kursziel € | bis zum Ziel |", "|---|---|:---:|---:|---:|---:|---:|"]
    for a in abstauber[:25]:
        euro = lambda v: f"{v:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
        z.append(f"| {a['name']} ({a['ticker']}) | {a['liste']} | {'ja' if a['im_depot'] else ''} | {f(a['seit_liste_eur'])} | {euro(a['kurs_eur'])} | {euro(a['ziel_eur'])} | {f(a['zum_ziel'])} |")
    z += ["", "Schwächste seit Erscheinen:", "", "| Titel | Liste | seit Liste (EUR) |", "|---|---|---:|"]
    for a in abstauber[-10:]:
        z.append(f"| {a['name']} ({a['ticker']}) | {a['liste']} | {f(a['seit_liste_eur'])} |")
    z += ["", "_Kurse von Yahoo Finance, um Splits und Dividenden bereinigt (Aktien). Vergangene Erholungen sagen nichts Sicheres über künftige._", ""]
    ZIEL_MD.write_text("\n".join(z), encoding="utf-8")
    print(f"{len(ergebnis_phasen)} Phasen, {len(rangliste)} Titel in der Rangliste, {len(abstauber)} Abstauber-Titel -> {ZIEL_MD}")


if __name__ == "__main__":
    main()
