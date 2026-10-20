"""Telegram-Versand für den Monitor.

Liest TELEGRAM_TOKEN aus .env. Die Chat-ID (TELEGRAM_CHAT_ID) wird beim ersten
Aufruf aus der letzten Nachricht an den Bot ermittelt und in .env ergänzt.

Aufruf zum Testen:  .venv/Scripts/python telegram.py "Testnachricht"
"""

import os
import sys
from pathlib import Path

from monitor import session

ENV = Path(__file__).parent / ".env"
MAX_LAENGE = 4000  # Telegram erlaubt 4096 Zeichen pro Nachricht


def lade_env():
    # GitHub Actions: Token und Chat-ID kommen als Secrets über Umgebungsvariablen
    werte = {k: os.environ[k] for k in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID") if os.environ.get(k)}
    if werte.get("TELEGRAM_TOKEN"):
        return werte
    if ENV.exists():
        for zeile in ENV.read_text(encoding="utf-8-sig").splitlines():
            if "=" in zeile and not zeile.strip().startswith("#"):
                k, v = zeile.split("=", 1)
                werte[k.strip()] = v.strip().strip('"').strip("'")
    return werte


def chat_id(s, token, env):
    if env.get("TELEGRAM_CHAT_ID"):
        return env["TELEGRAM_CHAT_ID"]
    antwort = s.get(f"https://api.telegram.org/bot{token}/getUpdates").json()
    for update in reversed(antwort.get("result", [])):
        chat = (update.get("message") or update.get("edited_message") or {}).get("chat")
        if chat and chat.get("type") == "private":
            with ENV.open("a", encoding="utf-8") as f:
                f.write(f"\nTELEGRAM_CHAT_ID={chat['id']}\n")
            return str(chat["id"])
    raise RuntimeError("Keine Chat-ID: Bitte dem Bot in Telegram zuerst eine Nachricht schreiben.")


def senden(text):
    env = lade_env()
    token = env.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN fehlt (GitHub: Settings > Secrets and variables > Actions > Repository secret TELEGRAM_TOKEN; lokal: .env)")
    s = session()
    ziel = chat_id(s, token, env)
    teile = [text[i:i + MAX_LAENGE] for i in range(0, len(text), MAX_LAENGE)] or [""]
    for teil in teile:
        r = s.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   json={"chat_id": ziel, "text": teil, "disable_web_page_preview": True}).json()
        if not r.get("ok"):
            raise RuntimeError(f"Telegram-Fehler: {r.get('description')}")


def melde(hinweise, titel="Marktmonitor"):
    """Wichtige Hinweise als eine Nachricht senden. Crash-Meldungen zuerst."""
    if not hinweise:
        return False
    sortiert = sorted(hinweise, key=lambda t: (not t.startswith(("Crash", "Erholung")), t))
    zeilen = [f"{titel}: {len(sortiert)} wichtige{'r' if len(sortiert) == 1 else ''} Hinweis{'' if len(sortiert) == 1 else 'e'}", ""]
    zeilen += [f"• {t}" for t in sortiert]
    senden("\n".join(zeilen))
    return True


if __name__ == "__main__":
    senden(" ".join(sys.argv[1:]) or "Testnachricht vom Marktmonitor.")
    print("gesendet")
