"""Aktienresearch-Monitor.

Holt Kurse von Yahoo Finance, prüft Marktlage, Watchlist, Portfolio und
Sektorrotation gegen die Schwellen aus config.yaml und schreibt einen Bericht
nach reports/. Neue Hinweise (seit dem letzten Lauf) stehen oben im Bericht
und in reports/latest.json, getrennt nach "wichtig" (für Push-Nachrichten)
und "weitere" (nur im Bericht).

Der Monitor gibt nur Hinweise. Er handelt nicht.

Aufruf:  .venv/Scripts/python monitor.py            voller Lauf mit Bericht und Dashboard
         .venv/Scripts/python monitor.py --schnell  nur Indizes, VIX und Crash-Muster (für häufige Läufe)

Rollen: Nur der "Läufer" (Umgebungsvariable AKTIEN_LAEUFER=1, gesetzt in GitHub Actions) schreibt den
gemeinsamen Meldestand (state.json, reports/, dashboard.html) und sendet Telegram. Auf Laptop und Büro-PC
schreibt ein Lauf nur in lokale Dateien (state_lokal.json, reports_lokal/, dashboard_lokal.html), damit
sich die Rechner nicht gegenseitig den Stand überschreiben oder Meldungen doppelt kommen.
"""

import csv
import json
import os
import shutil
import ssl
from datetime import datetime
from pathlib import Path

import argparse

import certifi
import numpy as np
import pandas as pd
import yaml
import yfinance as yf
from curl_cffi import requests as curl_requests

import crash
import dashboard
import fear_greed

BASIS = Path(__file__).parent
CONFIG = BASIS / "config.yaml"
PORTFOLIO = BASIS / "portfolio.csv"
ISIN_MAP = BASIS / "isin_map.yaml"
LISTEN = BASIS / "watchlisten.yaml"
LAEUFER = os.environ.get("AKTIEN_LAEUFER") == "1"
STATE = BASIS / ("state.json" if LAEUFER else "state_lokal.json")
REPORTS = BASIS / ("reports" if LAEUFER else "reports_lokal")
CA_BUNDLE = BASIS / "ca-bundle.pem"
KURS_CACHE = BASIS / ("kurs_cache.json" if LAEUFER else "kurs_cache_lokal.json")


def session():
    """curl-Session. Unter Windows mit den Zertifikaten des Systems (TLS-Inspektion im Firmennetz),
    sonst (z. B. GitHub Actions unter Linux) mit den Standard-Zertifikaten."""
    if os.name != "nt":
        return curl_requests.Session(impersonate="chrome")
    pems = [Path(certifi.where()).read_text()]
    for store in ("ROOT", "CA"):
        for der, enc, _ in ssl.enum_certificates(store):
            if enc == "x509_asn":
                pems.append(ssl.DER_cert_to_PEM_cert(der))
    CA_BUNDLE.write_text("\n".join(pems))
    return curl_requests.Session(impersonate="chrome", verify=str(CA_BUNDLE))


def fuelle_luecken(kurse, s, tage=15):
    """Yahoo lässt bei laufendem Handel gelegentlich den Vortag aus (z. B. alle europäischen Werte am
    09.10.2026 früh). Fehlende Schlusskurse der letzten Tage ergänzen: zuerst aus früheren Läufen
    (kurs_cache.json), sonst aus Stundenkursen (letzter Stundenwert des Tages)."""
    cache = json.loads(KURS_CACHE.read_text(encoding="utf-8")) if KURS_CACHE.exists() else {}
    kurse = kurse.copy()
    kurse.index = pd.to_datetime(kurse.index).normalize()
    fehlende = {pd.Timestamp(d) for werte in cache.values() for d in werte} - set(kurse.index)
    if fehlende:
        kurse = kurse.reindex(kurse.index.union(sorted(fehlende)))
    for sym, werte in cache.items():
        if sym not in kurse:
            continue
        for d, wert in werte.items():
            ts = pd.Timestamp(d)
            if pd.isna(kurse.at[ts, sym]):
                kurse.at[ts, sym] = wert

    # Noch Lücken? Titel, bei denen zwischen den letzten beiden Kursen ein Werktag fehlt, oder deren
    # letzter Kurs älter ist als der letzte Werktag vor heute (Vortag fehlt ganz, z. B. vor Börsenbeginn)
    letzter_werktag = np.busday_offset(datetime.now().date(), -1, roll="forward")
    luecke = []
    for sym in kurse.columns:
        v = kurse[sym].dropna()
        if len(v) >= 2 and (np.busday_count(v.index[-2].date(), v.index[-1].date()) > 1
                            or np.datetime64(v.index[-1].date()) < letzter_werktag):
            luecke.append(sym)
    if luecke:
        try:
            stunden = yf.download(luecke, period="5d", interval="60m", progress=False, session=s, auto_adjust=True)["Close"]
            if isinstance(stunden, pd.Series):
                stunden = stunden.to_frame(luecke[0])
            stunden.index = stunden.index.tz_convert("Europe/Berlin")
            tageswerte = stunden.groupby(stunden.index.date).last()
            for d, zeile in tageswerte.iterrows():
                ts = pd.Timestamp(d)
                if ts not in kurse.index:
                    kurse.loc[ts] = np.nan
                for sym in luecke:
                    if sym in zeile and pd.notna(zeile[sym]) and pd.isna(kurse.at[ts, sym]):
                        kurse.at[ts, sym] = zeile[sym]
            kurse = kurse.sort_index()
        except Exception as fehler:  # Lückenfüller darf den Lauf nicht abbrechen
            print(f"  Stundenkurse für Lücken nicht verfügbar: {fehler}")
    neu = {}
    for sym in kurse.columns:
        s = kurse[sym].dropna().iloc[-tage:]
        neu[sym] = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
    # Heutigen (noch laufenden) Tag nicht merken, er ändert sich bis Handelsschluss
    heute = datetime.now().strftime("%Y-%m-%d")
    for werte in neu.values():
        werte.pop(heute, None)
    cache.update(neu)
    KURS_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return kurse


def rsi(serie, n=14):
    delta = serie.diff()
    auf = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    ab = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + auf / ab)


def kennzahlen(serie):
    s = serie.dropna()
    if len(s) < 30:
        return None
    letzter = s.iloc[-1]
    hoch52 = s.iloc[-252:].max()
    sma200 = s.rolling(200).mean().iloc[-1] if len(s) >= 200 else None
    sma90 = s.rolling(90).mean().iloc[-1] if len(s) >= 90 else None

    def perf(tage):
        return (letzter / s.iloc[-tage - 1] - 1) * 100 if len(s) > tage else None

    jahresanfang = s[s.index.year < s.index[-1].year]
    return {
        "kurs": letzter,
        "datum": s.index[-1].strftime("%Y-%m-%d"),
        # Tagesveränderung nur, wenn kein Handelstag fehlt (Yahoo lässt gelegentlich Tage aus, z. B. ARGX.BR am 08.10.2026)
        "tag": (letzter / s.iloc[-2] - 1) * 100 if np.busday_count(s.index[-2].date(), s.index[-1].date()) <= 1 else None,
        "sma200": sma200,
        "abstand200": (letzter / sma200 - 1) * 100 if sma200 else None,
        "sma90": sma90,
        "abstand90": (letzter / sma90 - 1) * 100 if sma90 else None,
        "drawdown": (letzter / hoch52 - 1) * 100,
        "rsi": rsi(s).iloc[-1],
        "perf1m": perf(21),
        "perf3m": perf(63),
        "ytd": (letzter / jahresanfang.iloc[-1] - 1) * 100 if len(jahresanfang) else None,
    }


def hoechste_stufe(wert, stufen):
    """Höchste Stufe, die der Wert erreicht, sonst None."""
    return max((st for st in stufen if wert >= st), default=None)


def fmt(wert, nachkomma=1, prozent=False, vorzeichen=False):
    if wert is None or pd.isna(wert):
        return "–"
    text = f"{wert:+,.{nachkomma}f}" if vorzeichen else f"{wert:,.{nachkomma}f}"
    text = text.replace(",", "#").replace(".", ",").replace("#", ".")
    return text + (" %" if prozent else "")


def lade_portfolio():
    """portfolio.csv aus import_depot.py: ticker -> name, stueck, einstand {Währung: Betrag}."""
    if not PORTFOLIO.exists():
        return {}
    karte = yaml.safe_load(ISIN_MAP.read_text(encoding="utf-8")) if ISIN_MAP.exists() else {}
    portfolio = {}
    with PORTFOLIO.open(encoding="utf-8-sig") as f:
        for z in csv.DictReader(f, delimiter=";"):
            if not z["ticker"]:
                continue
            einstand = {}
            for teil in z["einstand"].split("|"):
                waehrung, betrag = teil.split("=")
                einstand[waehrung] = float(betrag)
            portfolio[z["ticker"]] = {
                "name": z["name"],
                "stueck": float(z["stueck"]),
                "einstand": einstand,
                "waehrung": (karte.get(z["isin"]) or {}).get("waehrung"),
            }
    return portfolio


class Hinweise:
    def __init__(self):
        self.liste = []  # (schlüssel, text, wichtig)

    def add(self, schluessel, text, wichtig=False):
        self.liste.append((schluessel, text, bool(wichtig)))


def main(schnell=False):
    if not LAEUFER and not STATE.exists() and (BASIS / "state.json").exists():
        shutil.copy(BASIS / "state.json", STATE)  # lokaler Lauf startet mit dem Stand des Läufers
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    sw = cfg["schwellen"]
    s = session()
    portfolio = {} if schnell else lade_portfolio()

    watch = {}
    for gruppe, titel in ({} if schnell else cfg["watchlist"]).items():
        for ticker, daten in titel.items():
            watch[ticker] = {"gruppe": gruppe, **(daten or {})}

    # Externe Listen (Google Finance, Abstauberlisten) aus import_listen.py
    listen = yaml.safe_load(LISTEN.read_text(encoding="utf-8")) if LISTEN.exists() and not schnell else {}
    listen_waehrung = listen.pop("_waehrungen", {}) if listen else {}
    mitglied = {}  # ticker -> [Listen]
    for schluessel, liste in listen.items():
        for ticker in liste["titel"]:
            mitglied.setdefault(ticker, []).append(schluessel)
    # Ausschlussliste: verschwindet aus Watchlist und Listen; im Depot wird der Titel weiter bewertet, aber nicht gemeldet
    ausschluss = set(cfg.get("ausschluss") or [])
    for liste in listen.values():
        liste["titel"] = {t: d for t, d in liste["titel"].items() if t not in ausschluss}
    watch = {t: w for t, w in watch.items() if t not in ausschluss}
    mitglied = {t: l for t, l in mitglied.items() if t not in ausschluss}
    abstauber = {t: {**d, "stand": l["stand"]} for sl, l in listen.items() if sl.startswith("abstauber") for t, d in l["titel"].items()}

    infos = {}
    for ticker in watch:
        try:
            infos[ticker] = yf.Ticker(ticker, session=s).info
        except Exception as fehler:  # einzelner Ticker darf den Lauf nicht abbrechen
            infos[ticker] = {"_fehler": str(fehler)}

    waehrungen = {p["waehrung"] for p in portfolio.values()} | {i.get("currency") for i in infos.values()}
    waehrungen |= {wa for p in portfolio.values() for wa in p["einstand"]}
    waehrungen |= set(listen_waehrung.values())
    basis = {"GBp": "GBP", "ZAc": "ZAR", "ILA": "ILS"}
    fx = sorted({f"EUR{basis.get(wa, wa)}=X" for wa in waehrungen if wa and basis.get(wa, wa) != "EUR"})

    symbole = list(dict.fromkeys(
        list(cfg["indizes"]) + [cfg["vix"], "SPY"] + ([] if schnell else list(cfg["sektoren"])) + list(watch) + list(portfolio) + list(mitglied) + fx
    ))
    daten = yf.download(symbole, period="2y", auto_adjust=True, actions=True, progress=False, session=s)
    kurse = fuelle_luecken(daten["Close"], s)
    splits = daten["Stock Splits"] if "Stock Splits" in daten else pd.DataFrame()
    k = {sym: kennzahlen(kurse[sym]) for sym in symbole if sym in kurse}

    def splitfaktor(ticker, seit):
        """Produkt aller Splits nach dem Datum, z. B. 10 bei einem 10:1-Split."""
        if ticker not in splits:
            return 1.0
        sp = splits[ticker]
        sp = sp[(sp.index >= pd.Timestamp(seit, tz=sp.index.tz)) & (sp > 0)]
        return float(sp.prod()) if len(sp) else 1.0

    def in_eur(betrag, waehrung):
        if betrag is None or not waehrung:
            return None
        if waehrung == "EUR":
            return betrag
        teiler = 100 if waehrung in ("GBp", "ZAc", "ILA") else 1
        rate = k.get(f"EUR{basis.get(waehrung, waehrung)}=X")
        return betrag / teiler / rate["kurs"] if rate else None

    # Portfolio bewerten (vor den Hinweisen, weil die Gewichtung zählt)
    positionen, pf_wert, pf_einstand = [], 0.0, 0.0
    for ticker, p in portfolio.items():
        m = k.get(ticker)
        wert = in_eur(m["kurs"] * p["stueck"], p["waehrung"]) if m else None
        einstand = sum(in_eur(b, wa) or 0 for wa, b in p["einstand"].items())
        if wert is not None:
            pf_wert += wert
            pf_einstand += einstand
        positionen.append({"ticker": ticker, **p, "m": m, "wert": wert, "einstand_eur": einstand})
    for pos in positionen:
        pos["gewicht"] = pos["wert"] / pf_wert * 100 if pos["wert"] and pf_wert else None

    h = Hinweise()

    # Marktlage: immer wichtig, das ist die Kernstrategie (Zukaufen in Panikphasen)
    for sym, name in cfg["indizes"].items():
        m = k.get(sym)
        if not m:
            continue
        if m["abstand200"] is not None:
            if m["abstand200"] < 0:
                h.add(f"{sym}:unter200", f"{name} notiert unter der 200-Tage-Linie ({fmt(m['abstand200'], prozent=True, vorzeichen=True)}).", True)
            elif m["abstand200"] <= sw["ma200_nah_prozent"]:
                h.add(f"{sym}:nah200", f"{name} nähert sich der 200-Tage-Linie: nur noch {fmt(m['abstand200'], prozent=True)} darüber.", True)
        if m["abstand90"] is not None and m["abstand90"] < 0:
            h.add(f"{sym}:unter90", f"{name} notiert unter der 90-Tage-Linie ({fmt(m['abstand90'], prozent=True, vorzeichen=True)}).")
        if m["tag"] is not None and m["tag"] <= -sw["index_tagesverlust"]:
            h.add(f"{sym}:tag:{m['datum']}", f"{name} fällt heute um {fmt(m['tag'], prozent=True)}.", True)
        stufe = hoechste_stufe(-m["drawdown"], sw["drawdown_stufen"])
        if stufe:
            h.add(f"{sym}:dd:{stufe}", f"{name} liegt {fmt(-m['drawdown'], prozent=True)} unter dem 52-Wochen-Hoch (Stufe {stufe} %).", True)
    vix = k.get(cfg["vix"])
    if vix:
        stufe = hoechste_stufe(vix["kurs"], sw["vix_stufen"])
        if stufe:
            h.add(f"VIX:{stufe}", f"VIX bei {fmt(vix['kurs'])} (Stufe {stufe}): erhöhte Angst im Markt.", stufe >= sw["vix_wichtig"])

    # Crash-/Korrekturmuster (crash.py): ab Korrektur sofort wichtig
    alt = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    jetzt = datetime.now()
    panik = None
    if cfg["crash_index"] in kurse and cfg["vix"] in kurse:
        verlauf = crash.verlauf(kurse[cfg["crash_index"]], kurse[cfg["vix"]])
        z = verlauf.iloc[-1]
        panik = {"score": int(z["score"]), "stufe": z["stufe"], "episoden": crash.episoden(verlauf)}
        if z["score"] >= 25:
            text = (f"Crash-Muster Stufe {z['stufe']} (Score {int(z['score'])}/100): {cfg['indizes'][cfg['crash_index']]} "
                    f"{fmt(z['r5'], prozent=True, vorzeichen=True)} in 5 Tagen, {fmt(-z['dd'], prozent=True)} unter Hoch, "
                    f"VIX {fmt(z['vix'])} ({fmt(z['vix5'], 0, True, True)} in 5 Tagen).")
            h.add(f"crash:{z['stufe']}", text, z["score"] >= 45)
        erh = crash.erholung(verlauf)
        letzte = alt.get("_letzte_erholung")
        if erh and (not letzte or (jetzt - datetime.fromisoformat(letzte)).days > 45):
            h.add("crash:erholung", f"Erholungssignal nach Stressphase seit {erh['seit']}: VIX von {fmt(erh['vix_spitze'])} auf {fmt(erh['vix'])} gefallen, "
                  f"{cfg['indizes'][cfg['crash_index']]} {fmt(erh['ueber_tief'], prozent=True)} über dem Tief. 2025 und 2026 war das ein guter Zeitpunkt zum Zukaufen.", True)

    def pruefe_titel(ticker, name, m, gewicht=None, kern=False):
        """kern = Titel aus der eigenen Watchlist in config.yaml; dort ist der Bruch der 200-Tage-Linie wichtig."""
        gross = gewicht is not None and gewicht >= sw["position_gross_prozent"]
        if m["tag"] is not None and m["tag"] <= -sw["aktie_tagesverlust"]:
            wichtig = m["tag"] <= -sw["aktie_tagesverlust_wichtig"] or gross
            h.add(f"{ticker}:tag:{m['datum']}", f"{name} fällt heute um {fmt(m['tag'], prozent=True)}.", wichtig)
        stufe = hoechste_stufe(-m["drawdown"], sw["drawdown_stufen"])
        if stufe:
            h.add(f"{ticker}:dd:{stufe}", f"{name} liegt {fmt(-m['drawdown'], prozent=True)} unter dem 52-Wochen-Hoch (Stufe {stufe} %).")
        if m["abstand200"] is not None:
            if m["abstand200"] < 0:
                h.add(f"{ticker}:unter200", f"{name} notiert unter der 200-Tage-Linie ({fmt(m['abstand200'], prozent=True, vorzeichen=True)}).", kern or gross)
            elif m["abstand200"] <= sw["ma200_nah_prozent"]:
                h.add(f"{ticker}:nah200", f"{name} nähert sich der 200-Tage-Linie: {fmt(m['abstand200'], prozent=True)} darüber.")
        if m["abstand90"] is not None:
            if m["abstand90"] < 0:
                h.add(f"{ticker}:unter90", f"{name} notiert unter der 90-Tage-Linie ({fmt(m['abstand90'], prozent=True, vorzeichen=True)}).")
            elif m["abstand90"] <= sw["ma90_nah_prozent"]:
                h.add(f"{ticker}:nah90", f"{name} nähert sich der 90-Tage-Linie: {fmt(m['abstand90'], prozent=True)} darüber.")

    def info_waehrung(ticker):
        if ticker in portfolio and portfolio[ticker]["waehrung"]:
            return portfolio[ticker]["waehrung"]
        return infos.get(ticker, {}).get("currency")

    # Frühwarnung Big Player: Stufen vom Hoch, 200T-Bruch, relative Schwäche, je Abwärtsphase nur einmal.
    # Eine Phase endet, wenn der Titel wieder weniger als 5 % unter dem Hoch steht.
    # Kauf- und Abstauberzonen: nur melden, wenn eine TIEFERE Zone erreicht wird (nicht beim Wiederanstieg von
    # unten, z. B. ServiceNow am 09.10.2026). Scharf erst wieder, wenn der Kurs 5 % über der ersten Zone liegt.
    zonen_alt = alt.get("_zonen")
    zonen_neu = {}

    def zone_neu_erreicht(schluessel, stufe, zuruecksetzen):
        bisher = 0 if zonen_alt is None else zonen_alt.get(schluessel, 0)
        if zuruecksetzen:
            bisher = 0
        neu = stufe > bisher and zonen_alt is not None  # beim allerersten Lauf nur merken, nicht melden
        zonen_neu[schluessel] = max(bisher, stufe) if not zuruecksetzen else 0
        return neu

    # Fear & Greed (CNN): extreme Angst war 2025/2026 ein guter Zeitpunkt zum Zukaufen. Gestaffelt, je Phase
    # jede Stufe einmal; neue Phase erst, wenn der Index wieder auf mindestens 45 (neutral) gestiegen ist.
    fg = fear_greed.abrufen(s, REPORTS / "fear_greed.json")
    fg_stand = dict(alt.get("_fg", {"stufe": 0}))
    if fg:
        stufen_fg = [(10, 3), (15, 2), (25, 1)]
        stufe = next((st for grenze, st in stufen_fg if fg["score"] <= grenze), 0)
        if fg["score"] >= sw["fear_greed_reset"]:
            fg_stand["stufe"] = 0
        if stufe > fg_stand["stufe"] and not fg.get("aus_cache"):
            grenze = {3: 10, 2: 15, 1: 25}[stufe]
            h.add(f"fg:{stufe}:{datetime.now():%Y-%m-%d}", f"Fear & Greed bei {fmt(fg['score'], 0)} ({fg['rating']}), unter {grenze}. "
                  f"Vorwoche {fmt(fg['vorwoche'], 0)}, Vormonat {fmt(fg['vormonat'], 0)}. Unter 10 lag 2025 und 2026 jeweils nahe am Tiefpunkt.", True)
            fg_stand["stufe"] = stufe
        if fg["score"] >= 80:
            h.add("fg:gier", f"Fear & Greed bei {fmt(fg['score'], 0)} (extreme Gier): viel Optimismus eingepreist.")

    bp_alt = alt.get("_bigplayer", {})
    bp_neu = {}
    index_1m = (k.get(cfg["crash_index"]) or {}).get("perf1m")

    def fruehwarnung(ticker, name, m, mit_90t=False):
        bw = sw["bigplayer"]
        z = {"max": 0, "u200": False, "rel": False, "u200_scharf": True, "u90": False, "u90_scharf": True, **bp_alt.get(ticker, {})}
        if -m["drawdown"] < bw["phase_ende_prozent"]:
            z.update(max=0, u200=False, rel=False, u90=False)
        if m["sma200"] and m["kurs"] >= m["sma200"] * 1.03:
            z["u200_scharf"] = True
        if m["sma90"] and m["kurs"] >= m["sma90"] * 1.03:
            z["u90_scharf"] = True
        # 90-Tage-Linie: früher Hinweis, dass das Momentum dreht (für stark gelaufene Titel wie Palantir)
        if mit_90t and m["abstand90"] is not None and m["abstand90"] < 0 and z["u90_scharf"] and not z["u90"]:
            h.add(f"{ticker}:bp:u90:{m['datum']}", f"Frühwarnung {name}: unter die 90-Tage-Linie gefallen ({fmt(m['abstand90'], prozent=True, vorzeichen=True)}), "
                  f"{fmt(-m['drawdown'], prozent=True)} unter dem Hoch.", True)
            z.update(u90=True, u90_scharf=False)
        stufe = hoechste_stufe(-m["drawdown"], bw["stufen"]) or 0
        if stufe > z["max"]:
            h.add(f"{ticker}:bp:dd{stufe}:{m['datum']}", f"Frühwarnung {name}: {fmt(-m['drawdown'], prozent=True)} unter dem 52-Wochen-Hoch (Stufe {stufe} %), "
                  f"Abstand 200T {fmt(m['abstand200'], prozent=True, vorzeichen=True)}.", True)
            z["max"] = stufe
        if m["abstand200"] is not None and m["abstand200"] < 0 and z["u200_scharf"] and not z["u200"]:
            h.add(f"{ticker}:bp:u200:{m['datum']}", f"Frühwarnung {name}: unter die 200-Tage-Linie gefallen ({fmt(m['abstand200'], prozent=True, vorzeichen=True)}).", True)
            z.update(u200=True, u200_scharf=False)
        if index_1m is not None and m["perf1m"] is not None and m["perf1m"] - index_1m <= -bw["rel_schwaeche_1m"] and not z["rel"]:
            h.add(f"{ticker}:bp:rel:{m['datum']}", f"Frühwarnung {name}: relative Schwäche, 1 Monat {fmt(m['perf1m'], prozent=True, vorzeichen=True)} "
                  f"gegen Nasdaq 100 {fmt(index_1m, prozent=True, vorzeichen=True)}.", True)
            z["rel"] = True
        bp_neu[ticker] = z

    # Watchlist
    for ticker, w in watch.items():
        m = k.get(ticker)
        name = f"{w['name']} ({ticker})"
        if not m:
            h.add(f"{ticker}:keinedaten", f"{name}: keine Kursdaten von Yahoo.")
            continue
        if w["gruppe"] == "zurueckgestellt":
            pruefe_titel(ticker, name, m)  # still: 200T-Bruch und Rücksetzer nur im Bericht
            continue
        if w["gruppe"] == "big_player" or w.get("fruehwarnung"):
            pruefe_titel(ticker, name, m)  # 200T-Bruch kommt hier über die Frühwarnung, nicht doppelt
            fruehwarnung(ticker, name, m, mit_90t=w.get("fruehwarnung_90t", False))
        else:
            pruefe_titel(ticker, name, m, kern=True)
        if m["rsi"] <= sw["rsi_ueberverkauft"]:
            h.add(f"{ticker}:rsi", f"{name} ist überverkauft (RSI {fmt(m['rsi'], 0)}).")
        if w.get("kaufzone") and m["kurs"] <= w["kaufzone"]:
            h.add(f"{ticker}:kaufzone", f"{name} ist in deiner Kaufzone ({fmt(m['kurs'], 2)} ≤ {fmt(w['kaufzone'], 2)}).", True)
        # Gestaffelte Kaufzonen in Euro (Nachkauf in Tranchen); gemeldet wird die tiefste erreichte
        if w.get("kaufzonen_eur"):
            kurs_eur = in_eur(m["kurs"], info_waehrung(ticker))
            zonen = sorted(w["kaufzonen_eur"], reverse=True)
            erreicht = [z for z in zonen if kurs_eur is not None and kurs_eur <= z]
            nr = len(erreicht)
            if kurs_eur is not None and zone_neu_erreicht(f"{ticker}:kaufzone_eur", nr, kurs_eur > zonen[0] * 1.05):
                h.add(f"{ticker}:kaufzone_eur:{nr}", f"{name} hat Kaufzone {nr} von {len(zonen)} erreicht: {fmt(kurs_eur, 2)} € ≤ {fmt(erreicht[-1], 2)} €"
                      + (f" (nächste Zone {fmt(zonen[nr], 2)} €)." if nr < len(zonen) else "."), True)
            elif nr == 0 and kurs_eur is not None and kurs_eur <= zonen[0] * (1 + sw["kaufzone_nah_prozent"] / 100):
                h.add(f"{ticker}:kaufzone_eur:nah", f"{name} nähert sich Kaufzone 1: {fmt(kurs_eur, 2)} €, Zone {fmt(zonen[0], 2)} €.")
        info = infos.get(ticker, {})
        rendite, schnitt = info.get("dividendYield"), info.get("fiveYearAvgDividendYield")
        if rendite and schnitt and rendite >= sw["dividende_min_rendite"] and rendite >= schnitt * (1 + sw["dividende_ueber_schnitt"] / 100):
            h.add(f"{ticker}:divrendite", f"{name}: Dividendenrendite {fmt(rendite, 2, True)} liegt deutlich über dem 5-Jahres-Schnitt von {fmt(schnitt, 2, True)}.")

    # Portfolio-Positionen, die nicht schon auf der Watchlist stehen
    for pos in positionen:
        if pos["ticker"] in watch or pos["ticker"] in ausschluss:
            continue
        if not pos["m"]:
            h.add(f"{pos['ticker']}:keinedaten", f"{pos['name']} ({pos['ticker']}): keine Kursdaten von Yahoo.")
            continue
        pruefe_titel(pos["ticker"], f"{pos['name']} ({pos['ticker']})", pos["m"], pos["gewicht"])

    # Titel nur aus externen Listen: nur starke Tagesverluste und tiefe Rücksetzer, sonst wird es zu viel
    nur_listen = [t for t in mitglied if t not in watch and t not in portfolio]
    for ticker in nur_listen:
        m = k.get(ticker)
        if not m:
            continue
        name = f"{next(l['titel'][ticker]['name'] for l in listen.values() if ticker in l['titel'])} ({ticker})"
        if m["tag"] is not None and m["tag"] <= -sw["aktie_tagesverlust_wichtig"]:
            h.add(f"{ticker}:tag:{m['datum']}", f"{name} fällt heute um {fmt(m['tag'], prozent=True)}.", True)
        stufe = hoechste_stufe(-m["drawdown"], [st for st in sw["drawdown_stufen"] if st >= 25])
        if stufe:
            h.add(f"{ticker}:dd:{stufe}", f"{name} liegt {fmt(-m['drawdown'], prozent=True)} unter dem 52-Wochen-Hoch (Stufe {stufe} %).")

    # Abstauberlisten: Kurs in EUR gegen Kauflimits
    def waehrung_von(ticker):
        if ticker in portfolio and portfolio[ticker]["waehrung"]:
            return portfolio[ticker]["waehrung"]
        return infos.get(ticker, {}).get("currency") or listen_waehrung.get(ticker)

    abstauber_zeilen = []
    for ticker, d in abstauber.items():
        m = k.get(ticker)
        kurs_eur = in_eur(m["kurs"], waehrung_von(ticker)) if m else None
        if kurs_eur is None:
            continue
        faktor = splitfaktor(ticker, d["stand"])
        if faktor == 1.0 and d.get("kurs_eur"):
            # Zweite Prüfung, falls Yahoo den Split nicht in den Aktionen führt (z. B. CrowdStrike 4:1, Juli 2026):
            # Kurs laut Liste gegen den bereinigten Kurs am Erscheinungstag
            reihe = kurse[ticker].dropna()
            start = reihe[reihe.index >= pd.Timestamp(d["stand"], tz=reihe.index.tz)]
            start_eur = in_eur(start.iloc[0], waehrung_von(ticker)) if len(start) else None
            if start_eur and d["kurs_eur"] / start_eur > 1.5:
                faktor = float(round(d["kurs_eur"] / start_eur))
        if faktor != 1.0:
            d = {**d, "name": f"{d['name']}, Limits split-bereinigt 1:{faktor:g}",
                 **{f: d[f] / faktor for f in ("limit1_eur", "limit2_eur", "ziel_eur")}}
        abstand1 = (kurs_eur / d["limit1_eur"] - 1) * 100
        abstauber_zeilen.append({"ticker": ticker, **d, "kurs_eur": kurs_eur, "abstand1": abstand1})
        name = f"{d['name']} ({ticker})"
        stufe = 2 if kurs_eur <= d["limit2_eur"] else 1 if kurs_eur <= d["limit1_eur"] else 0
        neu_tiefer = zone_neu_erreicht(f"{ticker}:abstauber", stufe, kurs_eur > d["limit1_eur"] * 1.05)
        if stufe == 2 and neu_tiefer:
            h.add(f"{ticker}:abstauber2", f"{name} unter Abstauber-Kauflimit 2: {fmt(kurs_eur, 2)} € ≤ {fmt(d['limit2_eur'], 2)} € (Ziel {fmt(d['ziel_eur'], 0)} €, Liste Stand 2025).", True)
        elif stufe == 1 and neu_tiefer:
            h.add(f"{ticker}:abstauber1", f"{name} hat Abstauber-Kauflimit 1 erreicht: {fmt(kurs_eur, 2)} € ≤ {fmt(d['limit1_eur'], 2)} € (Limit 2: {fmt(d['limit2_eur'], 2)} €, Liste Stand 2025).", True)
        elif stufe == 0 and abstand1 <= sw["abstauber_nah_prozent"]:
            h.add(f"{ticker}:abstauber_nah", f"{name} nähert sich Abstauber-Kauflimit 1: {fmt(kurs_eur, 2)} €, Limit {fmt(d['limit1_eur'], 2)} € ({fmt(abstand1, prozent=True, vorzeichen=True)}).")

    # Sektorrotation: Relative Stärke zum S&P 500
    spy = k.get("SPY")
    rotation = []
    for sym, name in cfg["sektoren"].items():
        m = k.get(sym)
        if m and spy:
            rotation.append({
                "symbol": sym, "name": name,
                "rel1m": m["perf1m"] - spy["perf1m"],
                "rel3m": m["perf3m"] - spy["perf3m"],
                "abstand200": m["abstand200"],
            })
    rotation.sort(key=lambda r: r["rel1m"], reverse=True)

    # Neu gegenüber dem letzten Lauf?
    aktiv = {sl: alt.get(sl, jetzt.isoformat(timespec="minutes")) for sl, _, _ in h.liste}
    neu = [(sl, t, wi) for sl, t, wi in h.liste if sl not in alt]
    aktiv["_fg"] = fg_stand
    if "crash:erholung" in aktiv:
        aktiv["_letzte_erholung"] = jetzt.isoformat(timespec="minutes")
    elif alt.get("_letzte_erholung"):
        aktiv["_letzte_erholung"] = alt["_letzte_erholung"]
    if schnell:
        # Nur Marktschlüssel wurden geprüft; alles andere aus dem letzten vollen Lauf behalten
        markt = tuple(f"{sym}:" for sym in cfg["indizes"]) + ("VIX:", "crash:", "fg:")
        aktiv.update({sl: w for sl, w in alt.items() if not sl.startswith(markt) and sl not in aktiv})
    else:
        aktiv["_bigplayer"] = bp_neu
        aktiv["_zonen"] = zonen_neu
        rotation_top = [r["symbol"] for r in rotation[:3]]
        if alt.get("_rotation_top") and set(rotation_top) != set(alt["_rotation_top"]):
            namen = ", ".join(r["name"] for r in rotation[:3])
            neu.append(("_rotation", f"Sektorrotation: Die stärksten Sektoren (1 Monat) sind jetzt {namen}.", False))
        aktiv["_rotation_top"] = rotation_top
    STATE.write_text(json.dumps(aktiv, indent=1, ensure_ascii=False), encoding="utf-8")
    neu_wichtig = [t for _, t, wi in neu if wi]
    neu_weitere = [t for _, t, wi in neu if not wi]

    if schnell:
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / "latest_schnell.json").write_text(json.dumps({
            "zeit": jetzt.isoformat(timespec="minutes"), "neu_wichtig": neu_wichtig, "neu_weitere": neu_weitere,
            "crash": {k_: v for k_, v in (panik or {}).items() if k_ != "episoden"},
            "fear_greed": {k_: v for k_, v in (fg or {}).items() if k_ != "historie"},
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"Schnellprüfung: Crash-Muster {panik['stufe'] if panik else '–'} ({panik['score'] if panik else '–'}/100), "
              f"Fear & Greed {fg['score'] if fg else '–'} ({fg['rating'] if fg else '–'}), {len(neu_wichtig)} neu und wichtig")
        for t in neu_wichtig:
            print(f"  ! {t}")
        return neu_wichtig

    # Bericht
    z = [f"# Marktbericht {jetzt:%d.%m.%Y %H:%M}", ""]
    z += ["## Neu und wichtig", ""] + ([f"- {t}" for t in neu_wichtig] or ["- nichts"])
    z += ["", "## Weitere neue Hinweise", ""] + ([f"- {t}" for t in neu_weitere] or ["- keine"])
    z += ["", "## Marktlage", "", "| Index | Stand | Tag | Abstand 90T | Abstand 200T | unter Hoch | 1 M | YTD |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for sym, name in cfg["indizes"].items():
        m = k.get(sym)
        if m:
            z.append(f"| {name} | {fmt(m['kurs'], 0)} | {fmt(m['tag'], prozent=True, vorzeichen=True)} | {fmt(m['abstand90'], prozent=True, vorzeichen=True)} | {fmt(m['abstand200'], prozent=True, vorzeichen=True)} | {fmt(m['drawdown'], prozent=True)} | {fmt(m['perf1m'], prozent=True, vorzeichen=True)} | {fmt(m['ytd'], prozent=True, vorzeichen=True)} |")
    if vix:
        z += ["", f"VIX: {fmt(vix['kurs'])} (Tag {fmt(vix['tag'], prozent=True, vorzeichen=True)})"]
    if fg:
        z += ["", f"Fear & Greed (CNN): {fmt(fg['score'], 0)} ({fg['rating']}), Vorwoche {fmt(fg['vorwoche'], 0)}, Vormonat {fmt(fg['vormonat'], 0)}"
                  + (" – letzter verfügbarer Stand" if fg.get("aus_cache") else "")]

    for gruppe in cfg["watchlist"]:
        z += ["", f"## Watchlist: {gruppe.replace('_', ' ').title()}", "",
              "| Titel | Kurs | Tag | unter Hoch | Abstand 90T | Abstand 200T | RSI | KGV fwd | Div.-Rendite (5J) |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        zeilen = [(t, w) for t, w in watch.items() if w["gruppe"] == gruppe and k.get(t)]
        zeilen.sort(key=lambda tw: k[tw[0]]["drawdown"])
        for ticker, w in zeilen:
            m, info = k[ticker], infos.get(ticker, {})
            div = info.get("dividendYield")
            div_text = f"{fmt(div, 2, True)} ({fmt(info.get('fiveYearAvgDividendYield'), 2, True)})" if div else "–"
            z.append(f"| {w['name']} | {fmt(m['kurs'], 2)} {info.get('currency', '')} | {fmt(m['tag'], prozent=True, vorzeichen=True)} | {fmt(m['drawdown'], prozent=True)} | {fmt(m['abstand90'], prozent=True, vorzeichen=True)} | {fmt(m['abstand200'], prozent=True, vorzeichen=True)} | {fmt(m['rsi'], 0)} | {fmt(info.get('forwardPE'))} | {div_text} |")

    if positionen:
        z += ["", "## Portfolio", ""]
        if pf_einstand:
            z += [f"Wert {fmt(pf_wert, 0)} EUR, Einstand {fmt(pf_einstand, 0)} EUR, Ergebnis {fmt(pf_wert - pf_einstand, 0, vorzeichen=True)} EUR ({fmt((pf_wert / pf_einstand - 1) * 100, prozent=True, vorzeichen=True)}). "
                  "Bewertet zu Yahoo-Kursen und aktuellen Devisenkursen, kann daher leicht vom Broker abweichen.", ""]
        z += ["| Titel | Gewicht | Wert (EUR) | seit Kauf | Tag | unter Hoch | Abstand 90T | Abstand 200T |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for pos in sorted(positionen, key=lambda p: p["wert"] or 0, reverse=True):
            m = pos["m"] or {}
            ergebnis = (pos["wert"] / pos["einstand_eur"] - 1) * 100 if pos["wert"] and pos["einstand_eur"] else None
            z.append(f"| {pos['name']} ({pos['ticker']}) | {fmt(pos['gewicht'], prozent=True)} | {fmt(pos['wert'], 0)} | {fmt(ergebnis, prozent=True, vorzeichen=True)} | {fmt(m.get('tag'), prozent=True, vorzeichen=True)} | {fmt(m.get('drawdown'), prozent=True)} | {fmt(m.get('abstand90'), prozent=True, vorzeichen=True)} | {fmt(m.get('abstand200'), prozent=True, vorzeichen=True)} |")

    if abstauber_zeilen:
        nah = sorted((r for r in abstauber_zeilen if r["abstand1"] <= 15), key=lambda r: r["abstand1"])
        z += ["", "## Abstauberlisten (aktienlust, Limits Stand 2025)", "",
              f"{len(nah)} von {len(abstauber_zeilen)} Titeln liegen höchstens 15 % über Kauflimit 1. Die Limits sind von 2025 und nicht mehr aktuell.", ""]
        if nah:
            z += ["| Titel | Kurs (EUR) | Limit 1 | Limit 2 | Ziel | Abstand zu Limit 1 | im Depot |", "|---|---:|---:|---:|---:|---:|:---:|"]
            for r in nah:
                z.append(f"| {r['name']} ({r['ticker']}) | {fmt(r['kurs_eur'], 2)} | {fmt(r['limit1_eur'], 2)} | {fmt(r['limit2_eur'], 2)} | {fmt(r['ziel_eur'], 0)} | {fmt(r['abstand1'], prozent=True, vorzeichen=True)} | {'ja' if r['ticker'] in portfolio else ''} |")

    if nur_listen:
        tief = sorted((t for t in nur_listen if k.get(t)), key=lambda t: k[t]["drawdown"])[:20]
        z += ["", "## Weitere Listen: größte Rücksetzer (nicht im Depot)", "",
              "| Titel | Listen | Tag | unter Hoch | Abstand 90T | Abstand 200T | RSI |", "|---|---|---:|---:|---:|---:|---:|"]
        for t in tief:
            m = k[t]
            name = next(l["titel"][t]["name"] for l in listen.values() if t in l["titel"])
            namen_listen = ", ".join(x.replace("google_", "").replace("abstauber_", "Abstauber ") for x in mitglied[t])
            z.append(f"| {name} ({t}) | {namen_listen} | {fmt(m['tag'], prozent=True, vorzeichen=True)} | {fmt(m['drawdown'], prozent=True)} | {fmt(m['abstand90'], prozent=True, vorzeichen=True)} | {fmt(m['abstand200'], prozent=True, vorzeichen=True)} | {fmt(m['rsi'], 0)} |")

    z += ["", "## Sektorrotation (relativ zum S&P 500)", "", "| Sektor | ETF | rel. 1 M | rel. 3 M | Abstand 200T |", "|---|---|---:|---:|---:|"]
    for r in rotation:
        z.append(f"| {r['name']} | {r['symbol']} | {fmt(r['rel1m'], prozent=True, vorzeichen=True)} | {fmt(r['rel3m'], prozent=True, vorzeichen=True)} | {fmt(r['abstand200'], prozent=True, vorzeichen=True)} |")

    z += ["", "## Alle aktiven Hinweise", ""] + ([f"- {'**!** ' if wi else ''}{t}" for _, t, wi in h.liste] or ["- keine"])
    z += ["", "_Datenquelle: Yahoo Finance über yfinance, Schlusskurse bzw. verzögerte Kurse. Keine Anlageberatung._", ""]

    REPORTS.mkdir(exist_ok=True)
    bericht = REPORTS / f"{jetzt:%Y-%m-%d_%H%M}.md"
    bericht.write_text("\n".join(z), encoding="utf-8")
    (REPORTS / "latest.json").write_text(json.dumps({
        "zeit": jetzt.isoformat(timespec="minutes"),
        "bericht": bericht.name,
        "neu_wichtig": neu_wichtig,
        "neu_weitere": neu_weitere,
        "aktiv": [t for _, t, _ in h.liste],
        "portfolio_wert_eur": round(pf_wert, 2),
        "portfolio_einstand_eur": round(pf_einstand, 2),
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    seite = dashboard.schreibe(
        jetzt=jetzt, cfg=cfg, k=k, kurse=kurse, watch=watch, infos=infos, positionen=positionen, pf_wert=pf_wert,
        pf_einstand=pf_einstand, mitglied=mitglied, listen=listen, abstauber_zeilen=abstauber_zeilen, rotation=rotation,
        hinweise=h.liste, neu_wichtig=neu_wichtig, neu_weitere=neu_weitere, ausschluss=ausschluss, panik=panik, fear_greed=fg,
        ziel_html=BASIS / ("dashboard.html" if LAEUFER else "dashboard_lokal.html"), ziel_daten=REPORTS / "daten.json")

    print(f"Bericht: {bericht}")
    print(f"Dashboard: {seite}")
    print(f"{len(neu_wichtig)} neu und wichtig, {len(neu_weitere)} weitere neue, {len(h.liste)} aktiv")
    for t in neu_wichtig:
        print(f"  ! {t}")
    return neu_wichtig


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aktienresearch-Monitor")
    parser.add_argument("--schnell", action="store_true", help="nur Indizes, VIX und Crash-Muster prüfen")
    parser.add_argument("--telegram", action="store_true", help="neue wichtige Hinweise per Telegram senden")
    argumente = parser.parse_args()
    wichtig = main(schnell=argumente.schnell)
    if argumente.telegram and not LAEUFER:
        print("Hinweis: Telegram sendet nur der Läufer (GitHub Actions, AKTIEN_LAEUFER=1). Lokaler Lauf: nichts gesendet.")
    elif argumente.telegram and wichtig:
        import telegram
        telegram.melde(wichtig)
        print("per Telegram gesendet")
