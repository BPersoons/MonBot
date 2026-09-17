"""Blokkeert elke aanroep naar api.telegram.org tijdens toetsen en pre-flight-controles.

Waarom (2026-09-17): toetsen en pre-flight-controles bouwen échte agents op. Zodra er lokaal
een bot-token te vinden is — `.env.adk` of Secret Manager via de eigen gcloud-login — sturen
die agents een ÉCHTE melding naar Bart. `tests/test_execution_fixes.py` deed dat bij elke
volledige run drie keer ("TRADE OPENED: BTC/USDC (Long) Entry: $45050 …"), en de
pre-deploy-poort en de controle-agent draaiden die run tientallen keren per dag. Bart zag
een reeks handelsmeldingen terwijl de handelspijplijn in productie al dagen uit stond.

Werking: `urllib.request.urlopen` en `requests.get/post` worden omwikkeld. Een URL naar
Telegram krijgt een nep-antwoord `{"ok": true, "result": []}` — goed genoeg voor zowel
sendMessage als getUpdates — en wordt (zonder token) vastgelegd in `ONDERSCHEPT`. Al het
andere verkeer gaat ongewijzigd door. Een toets die `urlopen` zelf patcht, vervangt deze
laag alleen binnen die toets; daarna staat de blokkade weer.

Dit bestand zit niet in de image (`tests/` staat in `.gcloudignore`).
"""
import io
import json
import re
import threading
import urllib.request

TELEGRAM_HOST = "api.telegram.org"
ONDERSCHEPT: list = []

_lock = threading.Lock()
_geinstalleerd = False


def _zonder_token(url: str) -> str:
    return re.sub(r"/bot[^/]+/", "/bot<token>/", str(url))


def _noteer(url) -> None:
    with _lock:
        ONDERSCHEPT.append(_zonder_token(url))


class _NepAntwoord(io.BytesIO):
    """Genoeg van een HTTP-antwoord voor alle verzenders in deze codebase."""

    status = 200

    def __init__(self):
        super().__init__(json.dumps({"ok": True, "result": []}).encode())

    def getcode(self):
        return 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def installeer() -> None:
    """Zet de blokkade aan. Idempotent: meermaals aanroepen is veilig."""
    global _geinstalleerd
    if _geinstalleerd:
        return

    echt_urlopen = urllib.request.urlopen

    def urlopen(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if TELEGRAM_HOST in url:
            _noteer(url)
            return _NepAntwoord()
        return echt_urlopen(req, *args, **kwargs)

    urllib.request.urlopen = urlopen

    try:
        import requests
    except ImportError:
        requests = None
    if requests is not None:
        for naam in ("get", "post"):
            echt = getattr(requests, naam)

            def omwikkeld(url, *args, _echt=echt, **kwargs):
                if TELEGRAM_HOST in str(url):
                    _noteer(url)
                    antwoord = requests.Response()
                    antwoord.status_code = 200
                    antwoord._content = json.dumps({"ok": True, "result": []}).encode()
                    return antwoord
                return _echt(url, *args, **kwargs)

            setattr(requests, naam, omwikkeld)

    _geinstalleerd = True
