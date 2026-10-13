"""Crash-/Korrekturmuster am Gesamtmarkt erkennen.

Score 0-100 aus vier Bausteinen, geeicht an Aug. 2024 (Yen-Carry), April 2025
(Zölle, Rosengarten) und März 2026:

- Nasdaq-100-Verlust über 5 Handelstage   bis 30 Punkte
- VIX-Niveau                              bis 30 Punkte
- VIX-Sprung über 5 Handelstage           bis 20 Punkte
- Abstand zum 52-Wochen-Hoch              bis 20 Punkte

Stufen: Ruhe < 25 ≤ Nervosität < 45 ≤ Korrektur < 65 ≤ Panik.
Historisch: Aug. 2024 = 75 (Panik), April 2025 = 100 (Panik), März 2026 = 55 (Korrektur).

Zusätzlich ein Erholungssignal: Nach Korrektur oder Panik in den letzten 30 Tagen
ist der VIX um mindestens 25 % von seiner Spitze gefallen und der Index liegt
mindestens 3 % über seinem Tief. Das war 2025 der Moment, in dem Zukaufen aufging.
"""

import pandas as pd

STUFEN = [(65, "Panik"), (45, "Korrektur"), (25, "Nervosität"), (0, "Ruhe")]
SCHLEICHEND_DD = 10    # % unter dem 52-Wochen-Hoch
SCHLEICHEND_A200 = 3   # höchstens so viel % über der 200-Tage-Linie


def _punkte(wert, schwellen):
    """schwellen: [(grenze, punkte), ...] absteigend; erste erreichte Grenze zählt."""
    for grenze, punkte in schwellen:
        if wert >= grenze:
            return punkte
    return 0


def stufe(score):
    return next(name for grenze, name in STUFEN if score >= grenze)


def verlauf(index, vix):
    """Tageswerte von Score und Bausteinen. index, vix: Schlusskurs-Serien."""
    df = pd.concat({"index": index, "vix": vix}, axis=1).ffill().dropna()
    df["r5"] = (df["index"] / df["index"].shift(5) - 1) * 100
    df["vix5"] = (df["vix"] / df["vix"].shift(5) - 1) * 100
    df["dd"] = (df["index"] / df["index"].rolling(252, min_periods=60).max() - 1) * 100
    df["a200"] = (df["index"] / df["index"].rolling(200, min_periods=150).mean() - 1) * 100
    df = df.dropna()
    df["score"] = [
        _punkte(-z.r5, [(8, 30), (5, 20), (3, 10)])
        + _punkte(z.vix, [(40, 30), (30, 25), (25, 15), (20, 5)])
        + _punkte(z.vix5, [(60, 20), (30, 10)])
        + _punkte(-z.dd, [(18, 20), (12, 10), (8, 5)])
        for z in df.itertuples()
    ]
    # Schleichende Korrektur (wie Aug.-Okt. 2023): Index deutlich unter Hoch und an der
    # 200-Tage-Linie, VIX bleibt ruhig. Mindestens Stufe Korrektur.
    df["schleichend"] = (df["dd"] <= -SCHLEICHEND_DD) & (df["a200"] <= SCHLEICHEND_A200)
    df.loc[df["schleichend"], "score"] = df.loc[df["schleichend"], "score"].clip(lower=45)
    df["stufe"] = df["score"].map(stufe)
    return df


def erholung(df, tage=30):
    """Erholungssignal nach Korrektur/Panik, sonst None."""
    fenster = df.iloc[-tage:]
    stress = fenster[fenster["score"] >= 45]
    if stress.empty:
        return None
    spitze = stress["score"].idxmax()
    nach = df.loc[spitze:]
    vix_spitze = nach["vix"].max()
    tief = nach["index"].min()
    jetzt = df.iloc[-1]
    if jetzt["vix"] <= vix_spitze * 0.75 and jetzt["index"] >= tief * 1.03 and jetzt["score"] < 45:
        return {"seit": spitze.strftime("%Y-%m-%d"), "vix_spitze": vix_spitze, "vix": jetzt["vix"],
                "ueber_tief": (jetzt["index"] / tief - 1) * 100}
    return None


def episoden(df, mindest=45):
    """Zusammenhängende Phasen ab Korrektur, für den Rückblick im Dashboard."""
    phasen, aktuell = [], None
    for datum, z in df.iterrows():
        if z["score"] >= mindest:
            if aktuell is None:
                aktuell = {"von": datum, "bis": datum, "max": z["score"], "dd": z["dd"], "vix": z["vix"]}
            else:
                aktuell.update(bis=datum, max=max(aktuell["max"], z["score"]), dd=min(aktuell["dd"], z["dd"]), vix=max(aktuell["vix"], z["vix"]))
        elif aktuell is not None and (datum - aktuell["bis"]).days > 10:
            phasen.append(aktuell)
            aktuell = None
    if aktuell is not None:
        phasen.append(aktuell)
    return [{"von": p["von"].strftime("%d.%m.%Y"), "bis": p["bis"].strftime("%d.%m.%Y"), "max": int(p["max"]),
             "stufe": stufe(p["max"]), "dd": round(float(p["dd"]), 1), "vix": round(float(p["vix"]), 1)} for p in phasen]
