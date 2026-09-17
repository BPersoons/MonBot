"""De Telegram-blokkade voor toetsen: echte agents mogen Bart vanuit een toets niets sturen.

Aanleiding (2026-09-17): Bart kreeg tientallen "TRADE OPENED: BTC/USDC … $45050"-meldingen.
Dat waren de waarden uit tests/test_execution_fixes.py, verstuurd door de échte
`agents.execution_agent._send_telegram` bij elke volledige toetsrun.
"""
import json
import urllib.request

from tests import telegram_blokkade as tb


def test_blokkade_is_actief_tijdens_toetsen():
    assert tb._geinstalleerd, "conftest hoort de blokkade bij het laden aan te zetten"


def test_urllib_naar_telegram_wordt_onderschept():
    voor = len(tb.ONDERSCHEPT)
    with urllib.request.urlopen("https://api.telegram.org/bot123:GEHEIM/sendMessage") as r:
        assert json.loads(r.read())["ok"] is True
    assert len(tb.ONDERSCHEPT) == voor + 1
    assert tb.ONDERSCHEPT[-1].endswith("/bot<token>/sendMessage")
    assert "GEHEIM" not in tb.ONDERSCHEPT[-1], "het token hoort nergens bewaard te worden"


def test_requests_naar_telegram_wordt_onderschept():
    import requests
    voor = len(tb.ONDERSCHEPT)
    r = requests.post("https://api.telegram.org/bot123:GEHEIM/sendMessage", json={"text": "x"})
    assert r.status_code == 200 and r.json()["ok"] is True
    r = requests.get("https://api.telegram.org/bot123:GEHEIM/getUpdates")
    assert r.json()["result"] == [], "getUpdates moet een lege lijst geven"
    assert len(tb.ONDERSCHEPT) == voor + 2


def test_ander_verkeer_gaat_gewoon_door():
    """Alleen Telegram wordt geblokkeerd; een data-URL bewijst dat zonder netwerk."""
    with urllib.request.urlopen("data:text/plain,hallo") as r:
        assert r.read() == b"hallo"


def test_het_echte_spampad_uit_de_executie_agent_is_dicht(monkeypatch):
    """Precies de functie die de nep-handelsmeldingen verstuurde."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:GEHEIM")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    from agents import execution_agent
    voor = len(tb.ONDERSCHEPT)
    execution_agent._send_telegram("TRADE OPENED: BTC/USDC (Long)\nEntry: $45050.0000")
    assert len(tb.ONDERSCHEPT) == voor + 1, "de melding had onderschept moeten worden"
    assert tb.ONDERSCHEPT[-1].endswith("/sendMessage")
