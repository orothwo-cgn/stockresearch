"""CNN Fear & Greed Index (0 = extreme Angst, 100 = extreme Gier).

Holt den aktuellen Wert und die Historie seit 2022 von CNN und merkt sich den letzten
erfolgreichen Abruf in reports/fear_greed.json (Ersatz, falls CNN einmal nicht antwortet).

Rückblick 2022-2026 (Nasdaq 100 drei Monate nach dem Tiefpunkt):
- unter 10: Mai 2022 +13,6 %, April 2025 +33,6 %, Nov. 2025 +3,8 %, März 2026 +31,9 %
- unter 25 allein: häufig, im Bärenmarkt 2022 mehrfach zu früh
"""

import json
from datetime import datetime
from pathlib import Path

CACHE = Path(__file__).parent / "reports" / "fear_greed.json"
URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2022-01-01"
KOPF = {"Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"}
STUFEN_DE = {"extreme fear": "extreme Angst", "fear": "Angst", "neutral": "neutral",
             "greed": "Gier", "extreme greed": "extreme Gier"}


def abrufen(s, cache=CACHE):
    """{'score', 'rating', 'vorwoche', 'vormonat', 'historie': [[datum, wert], ...], 'stand', 'aus_cache'} oder None."""
    try:
        d = s.get(URL, headers=KOPF, timeout=20).json()
        fg = d["fear_and_greed"]
        historie = [[datetime.fromtimestamp(x["x"] / 1000).strftime("%Y-%m-%d"), round(x["y"], 1)]
                    for x in d["fear_and_greed_historical"]["data"]]
        ergebnis = {
            "score": round(fg["score"], 1),
            "rating": STUFEN_DE.get(fg["rating"], fg["rating"]),
            "vorwoche": round(fg["previous_1_week"], 1),
            "vormonat": round(fg["previous_1_month"], 1),
            "historie": historie,
            "stand": datetime.now().isoformat(timespec="minutes"),
            "aus_cache": False,
        }
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(ergebnis, ensure_ascii=False), encoding="utf-8")
        return ergebnis
    except Exception as fehler:
        print(f"  Fear & Greed nicht abrufbar ({type(fehler).__name__}), nutze letzten Stand")
        if cache.exists():
            alt = json.loads(cache.read_text(encoding="utf-8"))
            alt["aus_cache"] = True
            return alt
        return None
