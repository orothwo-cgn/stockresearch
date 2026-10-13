"""Schreibt dashboard.html aus den Daten eines Monitor-Laufs.

Die Seite ist eine einzelne Datei ohne Server: Daten werden als JSON in
dashboard_vorlage.html eingesetzt. Im Browser öffnen (Doppelklick genügt).
"""

import json
import math
from pathlib import Path

BASIS = Path(__file__).parent
VORLAGE = BASIS / "dashboard_vorlage.html"
ZIEL = BASIS / "dashboard.html"

LISTEN_NAMEN = {
    "google_beobachtungsliste": "Beobachtungsliste",
    "google_bloch_live": "BLOCH LIVE",
    "google_golden_eye": "Golden Eye",
    "google_payoff": "PAYOFF",
    "google_medizin": "medizin",
    "abstauber_usa": "Abstauber USA",
    "abstauber_europa": "Abstauber Europa",
}


def zahl(x, stellen=5):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return float(f"{x:.{stellen}g}")


def schreibe(*, jetzt, cfg, k, kurse, watch, infos, positionen, pf_wert, pf_einstand,
             mitglied, listen, abstauber_zeilen, rotation, hinweise, neu_wichtig, neu_weitere, ausschluss, panik=None, fear_greed=None,
             ziel_html=ZIEL, ziel_daten=BASIS / "reports" / "daten.json"):
    namen = {}
    for liste in listen.values():
        for t, d in liste["titel"].items():
            namen.setdefault(t, d["name"].split(", Limits")[0])
    for t, w in watch.items():
        namen[t] = w["name"]
    for pos in positionen:
        namen.setdefault(pos["ticker"], pos["name"])

    depot = {p["ticker"]: p for p in positionen}
    abst = {r["ticker"]: r for r in abstauber_zeilen}
    alle = list(dict.fromkeys(list(watch) + list(depot) + list(mitglied)))

    titel = []
    for t in alle:
        m = k.get(t) or {}
        eintrag = {
            "t": t, "name": namen.get(t, t),
            "wa": (infos.get(t, {}) or {}).get("currency") or (depot[t]["waehrung"] if t in depot else None),
            "kurs": zahl(m.get("kurs")), "tag": zahl(m.get("tag"), 3), "dd": zahl(m.get("drawdown"), 3),
            "a90": zahl(m.get("abstand90"), 3), "a200": zahl(m.get("abstand200"), 3), "rsi": zahl(m.get("rsi"), 3),
            "p3m": zahl(m.get("perf3m"), 3), "ytd": zahl(m.get("ytd"), 3),
            "listen": mitglied.get(t, []), "gruppe": watch[t]["gruppe"] if t in watch else None,
            "aus": t in ausschluss,
        }
        if t in depot:
            p = depot[t]
            erg = (p["wert"] / p["einstand_eur"] - 1) * 100 if p["wert"] and p["einstand_eur"] else None
            eintrag["depot"] = {"wert": zahl(p["wert"], 7), "gew": zahl(p["gewicht"], 3), "erg": zahl(erg, 4), "stueck": p["stueck"]}
        if t in abst:
            r = abst[t]
            eintrag["ab"] = {"l1": zahl(r["limit1_eur"]), "l2": zahl(r["limit2_eur"]), "ziel": zahl(r["ziel_eur"]),
                             "keur": zahl(r["kurs_eur"]), "abst": zahl(r["abstand1"], 3),
                             "split": "split-bereinigt" in r["name"]}
        titel.append(eintrag)

    markt = []
    for sym, name in list(cfg["indizes"].items()) + [(cfg["vix"], "VIX")]:
        m = k.get(sym)
        if m:
            markt.append({"t": sym, "name": name, "kurs": zahl(m["kurs"]), "tag": zahl(m["tag"], 3),
                          "a90": zahl(m["abstand90"], 3), "a200": zahl(m["abstand200"], 3),
                          "dd": zahl(m["drawdown"], 3), "p1m": zahl(m["perf1m"], 3), "ytd": zahl(m["ytd"], 3)})

    sektoren = [{"t": r["symbol"], "name": r["name"], "rel1m": zahl(r["rel1m"], 3), "rel3m": zahl(r["rel3m"], 3),
                 "a200": zahl(r["abstand200"], 3)} for r in rotation]
    for name in sektoren:
        namen[name["t"]] = name["name"]
    for m in markt:
        namen[m["t"]] = m["name"]

    # Kursreihen (2 Jahre) für die Charts
    reihen_ticker = [t for t in alle + [m["t"] for m in markt] + [s["t"] for s in sektoren] if t in kurse]
    reihen = {t: [zahl(v) for v in kurse[t].tolist()] for t in dict.fromkeys(reihen_ticker)}

    daten = {
        "stand": jetzt.strftime("%d.%m.%Y %H:%M"),
        "depot": {"wert": zahl(pf_wert, 8), "einstand": zahl(pf_einstand, 8)},
        "markt": markt,
        "panik": panik,
        "fear_greed": {k: v for k, v in (fear_greed or {}).items() if k != "historie"} or None,
        "neu_wichtig": neu_wichtig,
        "neu_weitere": neu_weitere,
        "aktiv": [{"text": text, "wichtig": wichtig} for _, text, wichtig in hinweise],
        "titel": titel,
        "sektoren": sektoren,
        "listen": {k_: LISTEN_NAMEN.get(k_, k_) for k_, l in listen.items() if l["titel"]},
        "schwellen": {"nah200": cfg["schwellen"]["ma200_nah_prozent"], "nah90": cfg["schwellen"]["ma90_nah_prozent"]},
        "daten": [d.strftime("%Y-%m-%d") for d in kurse.index],
        "reihen": reihen,
        "namen": namen,
    }
    # Kompakte Fassung ohne Kursreihen für den Recherche-Agenten
    kompakt = {k_: v for k_, v in daten.items() if k_ not in ("daten", "reihen", "namen")}
    ziel_daten.parent.mkdir(exist_ok=True)
    ziel_daten.write_text(json.dumps(kompakt, ensure_ascii=False, indent=1), encoding="utf-8")

    json_text = json.dumps(daten, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    ziel_html.write_text(VORLAGE.read_text(encoding="utf-8").replace("/*__DATEN__*/null", json_text), encoding="utf-8")
    return ziel_html
