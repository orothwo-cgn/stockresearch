"""Wochenübersicht per Telegram, freitags nach US-Börsenschluss.

Baut den Text aus den Daten des letzten vollen Laufs (reports/daten.json):
Wochenbilanz von Depot und Indizes, Kaufzonen, größte Bewegungen im Depot,
Termine der nächsten Woche, Dividenden-Schätzung.

Vorschau lokal (sendet nichts):  .venv/Scripts/python wochenuebersicht.py
"""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASIS = Path(__file__).parent
SENDETAG = 4        # Freitag
AB_STUNDE = 22      # Berlin; der US-Lauf um 16:10 New York liegt nach 22 Uhr


def _p(v, d=1):
    if v is None:
        return "–"
    return ("+" if v > 0 else "") + f"{v:.{d}f}".replace(".", ",") + " %"


def _e(v, d=0):
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def text(daten, heute=None):
    heute = heute or date.today()
    titel = [t for t in daten["titel"] if t.get("gruppe") or t.get("depot")]
    depot = [t for t in titel if t.get("depot") and t["depot"].get("wert")]
    z = [f"Wochenübersicht KW {heute.isocalendar().week} (Stand {daten['stand']})", ""]

    # Depot und Indizes
    wert = sum(t["depot"]["wert"] for t in depot)
    vorher = sum(t["depot"]["wert"] / (1 + t["p1w"] / 100) if t.get("p1w") is not None else t["depot"]["wert"] for t in depot)
    if wert and vorher:
        z.append(f"Depot: {_e(wert)} ({_p((wert / vorher - 1) * 100)} in der Woche, {'+' if wert >= vorher else '−'}{_e(abs(wert - vorher))})")
    idx = [f"{m['name']} {_p(m.get('p1w'))}" for m in daten["markt"] if m["name"] != "VIX"]
    vix = next((m for m in daten["markt"] if m["name"] == "VIX"), None)
    z.append("Indizes: " + ", ".join(idx) + (f", VIX {vix['kurs']:.1f}".replace(".", ",") if vix else ""))
    if daten.get("fear_greed"):
        f = daten["fear_greed"]
        z.append(f"Fear & Greed: {f.get('score', 0):.0f} ({f.get('rating', '')})")
    if daten.get("panik"):
        z.append(f"Crash-Muster: {daten['panik']['stufe']} (Score {daten['panik']['score']})")

    # Kaufzonen
    erreicht, nah = [], []
    for t in titel:
        if not t.get("zonen") or t.get("keur") is None:
            continue
        n = sum(1 for zz in t["zonen"] if t["keur"] <= zz)
        abst = (t["zonen"][0] / t["keur"] - 1) * 100
        if n:
            erreicht.append(f"- {t['name']}: {_e(t['keur'], 2)}, Zone {n} von {len(t['zonen'])} ({_e(t['zonen'][n - 1], 2)})")
        elif abst >= -8:
            nah.append((abst, f"- {t['name']}: {_e(t['keur'], 2)}, Zone 1 bei {_e(t['zonen'][0], 2)} ({_p(abst)})"))
    z += ["", "In der Kaufzone:"] + (erreicht or ["- keine"])
    z += ["", "Nah an Kaufzone 1 (bis 8 %):"] + ([x for _, x in sorted(nah, reverse=True)] or ["- keine"])

    # Bewegungen im Depot (nur Positionen ab 0,3 % Gewicht, sonst rauschen Kleinstpositionen)
    rel = [t for t in depot if t.get("p1w") is not None and (t["depot"].get("gew") or 0) >= 0.3]
    rel.sort(key=lambda t: t["p1w"])
    if rel:
        z += ["", "Schwächste im Depot:"] + [f"- {t['name']} {_p(t['p1w'])}" for t in rel[:5]]
        z += ["", "Stärkste im Depot:"] + [f"- {t['name']} {_p(t['p1w'])}" for t in rel[::-1][:3]]

    # Termine nächste Woche
    von, bis = heute + timedelta(days=1), heute + timedelta(days=9)
    termine = []
    for t in titel:
        sd = t.get("sd") or {}
        for feld, art in (("zahlen", "Zahlen"), ("exdiv", "Ex-Dividende")):
            if feld == "exdiv" and not t.get("depot"):
                continue  # Ex-Tag nur für eigene Positionen interessant
            if sd.get(feld):
                d = date.fromisoformat(sd[feld])
                if von <= d <= bis:
                    termine.append((d, f"- {d:%a %d.%m.}: {art} {t['name']}" + ("" if t.get("depot") else " (beobachtet)")))
    tage = {"Mon": "Mo", "Tue": "Di", "Wed": "Mi", "Thu": "Do", "Fri": "Fr", "Sat": "Sa", "Sun": "So"}
    zeilen = [x for _, x in sorted(termine)]
    for en, de in tage.items():
        zeilen = [x.replace(f"- {en} ", f"- {de} ") for x in zeilen]
    z += ["", "Termine nächste Woche:"] + (zeilen or ["- keine"])

    # Dividenden
    div = sum(t["depot"].get("div_eur") or 0 for t in depot)
    if div:
        z += ["", f"Dividenden-Schätzung: ca. {_e(div)} pro Jahr brutto, Schnitt {_e(div / 12)} im Monat."]
    z += ["", "Details im Dashboard (Übersicht)."]
    return "\n".join(z)


def faellig(state, jetzt=None):
    """Freitag ab 22 Uhr, einmal pro Kalenderwoche."""
    jetzt = jetzt or datetime.now()
    woche = f"{jetzt.isocalendar().year}-{jetzt.isocalendar().week}"
    return jetzt.weekday() == SENDETAG and jetzt.hour >= AB_STUNDE and state.get("_wochenuebersicht") != woche, woche


def pruefe_und_sende(daten_pfad, state_pfad):
    state = json.loads(state_pfad.read_text(encoding="utf-8")) if state_pfad.exists() else {}
    ja, woche = faellig(state)
    if not ja:
        return False
    import telegram
    telegram.senden(text(json.loads(daten_pfad.read_text(encoding="utf-8"))))
    state["_wochenuebersicht"] = woche
    state_pfad.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    pfad = BASIS / "reports_lokal" / "daten.json"
    if not pfad.exists():
        pfad = BASIS / "reports" / "daten.json"
    print(text(json.loads(pfad.read_text(encoding="utf-8"))))
