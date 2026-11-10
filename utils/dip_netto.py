"""Netto resultaat van de dip-koper uit de bron: Hyperliquid-fills en funding.

H1 telde tot 10-11 het eigen boek (`realized_pnl_usd`). Dat ging op drie punten mis:
- geen fees en geen funding (A4 03-11, bevinding 6);
- de reeks begon pas op 16-09, terwijl rente en kosten vanaf 15-08 meetelden: de winsten van
  de eerste maand vielen weg (A1 10-11: $29,45);
- het boek rekent tegen de markprijs en overschrijft rondes per ticker
  (`scripts/dipkoper_resultaat.py`).

De KPI vraagt alleen verschillen binnen het venster, dus de reeks hoeft niet bij de start van
de wallet te beginnen. Elke dag wordt het hele venster opnieuw opgehaald: een gemiste dag
herstelt zichzelf. Een onvolledige ophaling mag nooit stil een getal worden: dan gaat er een
fout door en is H1 die dag onmeetbaar.
"""

import json
import logging
import math
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger("DipNetto")

INFO = "https://api.hyperliquid.xyz/info"
EIGEN_WALLET_VANAF = "2026-07-20"   # daarvoor liep de dip-koper via de hoofdwallet
VENSTER_DAGEN = 100                 # ruim boven het H1-venster (90), zodat gaten erin passen
MAX_DUUR_SEC = 60                   # de KPI-update draait in de hoofdlus
HERHAAL_POGINGEN = 3
HERHAAL_PAUZE_SEC = 2
MAX_FUNDING_LEEFTIJD_UUR = 26       # funding loopt minstens dagelijks zolang er een positie open staat


def _post(body):
    req = urllib.request.Request(INFO, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _nu_ms():
    return time.time() * 1000.0


def _post_met_herhaling(body, deadline):
    """Een storing van even mag geen alarm worden; aanhoudend falen gaat door naar de KPI."""
    laatste = None
    for poging in range(HERHAAL_POGINGEN):
        if time.monotonic() > deadline:
            raise TimeoutError("ophalen bij HL duurde langer dan %ss" % MAX_DUUR_SEC)
        try:
            return _post(body)
        except (OSError, ValueError) as e:      # URLError/HTTPError zijn OSError, geen JSON = ValueError
            laatste = e
            if poging < HERHAAL_POGINGEN - 1:
                time.sleep(HERHAAL_PAUZE_SEC)
    raise laatste


def _sleutel(x):
    """Identiteit van een regel. Funding van alle posities valt op exact dezelfde tijd."""
    return x["tid"] if "delta" not in x else (x["time"], x["delta"].get("coin"))


def _alles(soort, adres, start_ms, pagina, deadline):
    """Pagineert een info-endpoint dat maximaal `pagina` regels per keer geeft.

    Herstart op de laatste tijd (niet +1) en ontdubbelt: regels met dezelfde tijd kunnen
    over de paginagrens vallen (A1 10-11: 9 van 1.749 regels gingen zo verloren).
    """
    gezien, uit = set(), []
    while True:
        r = _post_met_herhaling({"type": soort, "user": adres, "startTime": start_ms}, deadline)
        if not r:
            break
        nieuw = [x for x in r if _sleutel(x) not in gezien]
        gezien.update(_sleutel(x) for x in nieuw)
        uit.extend(nieuw)
        if len(r) < pagina or not nieuw:
            break
        start_ms = max(x["time"] for x in r)
    return uit


def _getal(waarde):
    v = float(waarde)       # None of een leeg veld is een fout, geen nul
    if not math.isfinite(v):
        raise ValueError("niet-eindig bedrag in de HL-data: %r" % (waarde,))
    return v


def _dag(ms):
    return datetime.fromtimestamp(ms / 1000.0, timezone.utc).date().isoformat()


def netto_per_dag(fills, funding):
    """{datum: gerealiseerd - fees + funding}. Datum in UTC. Puur."""
    per = defaultdict(float)
    for f in fills:
        per[_dag(f["time"])] += _getal(f["closedPnl"]) - _getal(f["fee"])
    for x in funding:
        delta = x.get("delta") or {}
        if delta["type"] == "funding":
            # `usdc` is negatief als de long betaalt: optellen is dus aftrekken.
            per[_dag(x["time"])] += _getal(delta["usdc"])
    return dict(per)


def cumulatief(per_dag, begin, vandaag):
    """{datum: som van alles VOOR die datum}, voor elke kalenderdag van begin t/m vandaag.

    De snapshots vallen om 00:05 UTC, dus de stand 'op' een datum is alles tot die nacht.
    """
    d = date.fromisoformat(begin)
    eind = date.fromisoformat(vandaag)
    uit, som = {}, 0.0
    while d <= eind:
        uit[d.isoformat()] = som
        som += per_dag.get(d.isoformat(), 0.0)
        d += timedelta(days=1)
    return uit


def _controleer_volledigheid(adres, fills, funding, deadline):
    """Een lege of afgekapte respons is geen resultaat van $0."""
    if not fills and not funding:
        raise ValueError("HL gaf geen fills en geen funding over %d dagen: verkeerd adres of lege respons"
                         % VENSTER_DAGEN)
    staat = _post_met_herhaling({"type": "clearinghouseState", "user": adres, "dex": "xyz"}, deadline)
    if not any(_getal(p["position"]["szi"]) != 0 for p in staat["assetPositions"]):
        return
    if not fills:
        raise ValueError("posities open maar geen enkele fill in het venster: onvolledige ophaling")
    laatste = max((x["time"] for x in funding), default=None)
    if laatste is None or _nu_ms() - laatste > MAX_FUNDING_LEEFTIJD_UUR * 3600 * 1000:
        raise ValueError("posities open maar de laatste funding is te oud of ontbreekt: onvolledige ophaling")


def haal_cumulatief(adres, vandaag):
    """Cumulatieve netto-reeks over het venster. Een fout gaat door: onmeetbaar is geen nul."""
    begin = max(EIGEN_WALLET_VANAF,
                (date.fromisoformat(vandaag) - timedelta(days=VENSTER_DAGEN)).isoformat())
    start_ms = int(datetime.fromisoformat(begin).replace(tzinfo=timezone.utc).timestamp() * 1000)
    deadline = time.monotonic() + MAX_DUUR_SEC
    fills = _alles("userFillsByTime", adres, start_ms, 2000, deadline)
    funding = _alles("userFunding", adres, start_ms, 500, deadline)
    _controleer_volledigheid(adres, fills, funding, deadline)
    return cumulatief(netto_per_dag(fills, funding), begin, vandaag)
