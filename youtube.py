"""Neue Videos der Kanäle und Suchbegriffe aus config.yaml abholen und als Transkript ablegen.

- Kanäle (config: youtube): neue Videos über den RSS-Feed des Kanals.
- Suchen (config: youtube_suche): neue Videos zu einem Namen oder Begriff auf beliebigen Kanälen,
  z. B. Auftritte von Thomas Rappold bei WELT, Börse Online oder Divizend. Grundlage ist die
  YouTube-Suche, sortiert nach Upload-Datum.

Transkript (de, sonst en) nach transkripte/<JJJJ-MM-TT>_<quelle>_<video-id>.md. Die inhaltliche
Auswertung macht danach der Recherche-Agent. Beim allerersten Lauf einer Quelle werden nur
Videos der letzten 14 Tage geholt. Ein Video wird nur einmal gespeichert, auch wenn es über
mehrere Quellen gefunden wird.

Aufruf:  .venv/Scripts/python youtube.py
"""

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import truststore
import yaml
from youtube_transcript_api import YouTubeTranscriptApi

from monitor import session

truststore.inject_into_ssl()  # youtube-transcript-api nutzt requests; TLS-Inspektion auf diesem Rechner

BASIS = Path(__file__).parent
CONFIG = BASIS / "config.yaml"
STATE = BASIS / "youtube_state.json"
ZIEL = BASIS / "transkripte"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
ERSTLAUF_TAGE = 14
SUCHE_MAX_ALTER_TAGE = 7  # bei späteren Läufen nur Treffer, die höchstens so alt sind
EINHEITEN = {"min": 1 / 1440, "std": 1 / 24, "stunde": 1 / 24, "tag": 1, "woche": 7, "monat": 30, "jahr": 365}


def kurzname(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:30]


def alter_tage(text):
    """'vor 33 Min.', 'vor 3 Tagen', 'vor 2 Monaten' -> Tage (grob); unbekannt -> None."""
    m = re.search(r"(\d+)\s*([A-Za-zä]+)", text or "")
    if not m:
        return None
    zahl, einheit = int(m.group(1)), m.group(2).lower()
    for schluessel, tage in EINHEITEN.items():
        if einheit.startswith(schluessel):
            return zahl * tage
    return None


def suche(s, begriff):
    """Treffer der YouTube-Suche, neueste zuerst: (video_id, titel, kanal, alter_in_tagen)."""
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(begriff) + "&sp=CAI%253D"
    html = s.get(url, headers={"Accept-Language": "de-DE"}).text
    treffer = re.search(r"var ytInitialData = (\{.*?\});</script>", html)
    if not treffer:
        return []

    def videos(o):
        if isinstance(o, dict):
            if "videoRenderer" in o:
                yield o["videoRenderer"]
            for v in o.values():
                yield from videos(v)
        elif isinstance(o, list):
            for v in o:
                yield from videos(v)

    ergebnis = []
    for v in videos(json.loads(treffer.group(1))):
        titel = "".join(r.get("text", "") for r in v.get("title", {}).get("runs", []))
        kanal = (v.get("ownerText", {}).get("runs") or [{}])[0].get("text", "?")
        beschreibung = " ".join(r.get("text", "") for sn in v.get("detailedMetadataSnippets", [])
                                for r in sn.get("snippetText", {}).get("runs", []))
        ergebnis.append((v["videoId"], titel, kanal, alter_tage(v.get("publishedTimeText", {}).get("simpleText")), beschreibung))
    return ergebnis


def kanal_videos(s, kanal_id):
    """Ersatz für den RSS-Feed (der zeitweise 404 liefert): neueste Videos von der Videoseite des Kanals.
    Liefert (video_id, titel, alter_in_tagen)."""
    html = s.get(f"https://www.youtube.com/channel/{kanal_id}/videos", headers={"Accept-Language": "de-DE"},
                 cookies={"SOCS": "CAI", "CONSENT": "YES+cb"}).text
    treffer = re.search(r"var ytInitialData = (\{.*?\});</script>", html)
    if not treffer:
        return []

    def elemente(o):
        if isinstance(o, dict):
            if "lockupViewModel" in o:
                yield o["lockupViewModel"]
            for v in o.values():
                yield from elemente(v)
        elif isinstance(o, list):
            for v in o:
                yield from elemente(v)

    ergebnis = []
    for v in elemente(json.loads(treffer.group(1))):
        meta = v.get("metadata", {}).get("lockupMetadataViewModel", {})
        titel = meta.get("title", {}).get("content")
        alter = re.search(r"vor \d+\s*[A-Za-zä]+", json.dumps(meta, ensure_ascii=False))
        if v.get("contentId") and titel:
            ergebnis.append((v["contentId"], titel, alter_tage(alter.group(0)) if alter else None))
    return ergebnis


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    s = session()
    api = YouTubeTranscriptApi()
    ZIEL.mkdir(exist_ok=True)
    gespeichert = {p.stem.rsplit("_", 1)[-1] for p in ZIEL.glob("*.md")}
    neu = []

    def speichere(vid, titel, datum, quelle, kanal):
        if vid in gespeichert:
            return True
        try:
            teile = api.fetch(vid, languages=["de", "en"])
            text = " ".join(t.text for t in teile)
        except Exception as fehler:
            if type(fehler).__name__ == "TranscriptsDisabled":
                # Untertitel vom Kanal abgeschaltet: kommt nicht mehr, als erledigt merken
                print(f"  ohne Untertitel (übersprungen): {kanal}: {titel}")
                return True
            # Transkript fehlt oft noch kurz nach Upload: nicht als bekannt markieren, nächster Lauf versucht es erneut
            print(f"  ohne Transkript (später erneut): {kanal}: {titel} ({type(fehler).__name__})")
            return False
        datei = ZIEL / f"{datum:%Y-%m-%d}_{kurzname(quelle)}_{vid}.md"
        datei.write_text(
            f"# {titel}\n\n"
            f"- Kanal: {kanal}\n- Quelle: {quelle}\n- Datum: {datum:%d.%m.%Y}\n- Link: https://www.youtube.com/watch?v={vid}\n"
            f"- Ausgewertet: nein\n\n## Transkript\n\n{text}\n",
            encoding="utf-8",
        )
        gespeichert.add(vid)
        neu.append(datei.name)
        print(f"  neu: {kanal}: {titel}")
        return True

    for kanal in cfg.get("youtube", []):
        bekannt = set(state.get(kanal["id"], []))
        grenze = datetime.now(timezone.utc) - timedelta(days=ERSTLAUF_TAGE)
        try:
            feed = ET.fromstring(s.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={kanal['id']}").content)
            eintraege = [(e.find("yt:videoId", NS).text, e.find("a:title", NS).text,
                          datetime.fromisoformat(e.find("a:published", NS).text)) for e in feed.findall("a:entry", NS)]
        except ET.ParseError:
            # Feed liefert zeitweise 404/Fehlerseite: Videoseite des Kanals als Ersatz
            eintraege = [(vid, titel, datetime.now(timezone.utc) - timedelta(days=alter))
                         for vid, titel, alter in kanal_videos(s, kanal["id"]) if alter is not None]
            if not eintraege:
                print(f"  Feed und Videoseite nicht lesbar, später erneut: {kanal['name']}")
                continue
        for vid, titel, datum in eintraege:
            if vid in bekannt:
                continue
            # Ältere Videos nie nachholen (die Videoseite listet 30 statt 15 Videos und reicht weit zurück)
            if datum < grenze or (kanal.get("filter") and not any(f.lower() in titel.lower() for f in kanal["filter"])):
                bekannt.add(vid)
                continue
            if speichere(vid, titel, datum, kanal["name"], kanal["name"]):
                bekannt.add(vid)
        state[kanal["id"]] = sorted(bekannt)

    for eintrag in cfg.get("youtube_suche", []):
        schluessel = "suche:" + eintrag["begriff"]
        bekannt = set(state.get(schluessel, []))
        max_alter = ERSTLAUF_TAGE if schluessel not in state else SUCHE_MAX_ALTER_TAGE
        try:
            treffer = suche(s, eintrag["begriff"])
        except Exception as fehler:
            print(f"  Suche '{eintrag['begriff']}' fehlgeschlagen: {fehler}")
            continue
        for vid, titel, kanal, alter, beschreibung in treffer:
            if vid in bekannt:
                continue
            # Nur Videos, in denen der Name in Titel oder Beschreibung vorkommt (Suche liefert sonst auch Beifang)
            pflicht = eintrag.get("im_titel")
            if alter is None or alter > max_alter or (pflicht and pflicht.lower() not in (titel + " " + beschreibung).lower()):
                bekannt.add(vid)
                continue
            datum = datetime.now(timezone.utc) - timedelta(days=alter)
            if speichere(vid, titel, datum, eintrag["name"], kanal):
                bekannt.add(vid)
        state[schluessel] = sorted(bekannt)

    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print(f"{len(neu)} neue Transkripte in {ZIEL.name}/")


if __name__ == "__main__":
    main()
