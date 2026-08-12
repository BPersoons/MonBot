"""Divergentie-screen voor de dip-koper: zakten de fundamentals mee met de koers?

PLAN_2026-08 par. 4 noemt dit "de goedkoopste echte verbetering die er ligt". De
sleeve koopt op `pullback_z >= 1.5` — puur prijs, zonder enige toets of het bedrijf
zelf ook slechter werd. Deze filter scheidt dips die herstellen van dips die dat
nooit doen.

De sleeve handelt XYZ-synthetics op individuele bedrijven (XYZ-MSFT, XYZ-ORCL, ...),
dus er ís een onderliggende jaarrekening om naar te kijken.

## Wat er getoetst wordt

Twee signalen uit de kwartaalcijfers, beide uit research/README.md:

1. **Brutomarge-trend** — zakt de marge structureel mee met de koers, dan is de
   daling fundamenteel bevestigd en geen sentiment (README-rij 4: AFVALLER).
2. **Omzetgroei jaar-op-jaar** — krimpende omzet is dezelfde categorie.

Wat NIET getoetst wordt: de winstverrassing. Daarvoor is analistenconsensus nodig
en die is niet betrouwbaar uit een gratis bron te halen. Liever twee harde signalen
dan drie waarvan één gokwerk.

## Waarom fail-open

Kan een bedrijf niet gemeten worden (recente beursgang, ontbrekende cijfers), dan
BLOKKEERT deze filter niet. Reden: het is een extra screen bovenop de bestaande
risicobeheersing van de sleeve (downside-stop, sector-circuit-breaker), niet de
primaire vangrail. Fail-closed zou bij een storing in de databron de hele sleeve
stilzetten — precies het faalpatroon waarbij de sleeve vier dagen niets opende
zonder dat iemand het merkte. Onmeetbaar wordt wel geteld en gelogd.

## Bewuste duplicatie

De logica lijkt op research/fundamentals.py maar importeert die niet: `research/`
staat los van de swarm (zie CLAUDE.md) en die scheiding is meer waard dan het
vermijden van tachtig regels overlap.
"""

import json
import logging
import os
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

logger = logging.getLogger("DivergenceFilter")

CACHE_FILE = "divergence_cache.json"

# Brutomarge mag over vier kwartalen niet meer dan dit aantal procentpunten zakken.
MARGE_DALING_PP = 2.0
# Omzetgroei jaar-op-jaar onder deze grens telt als fundamentele verslechtering.
MIN_OMZETGROEI_PCT = 0.0


def _ticker(xyz: str) -> str:
    """'XYZ-MSFT' -> 'MSFT'."""
    return xyz.split("-", 1)[1] if "-" in xyz else xyz


def _cache_laden() -> dict:
    try:
        with open(CACHE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _cache_opslaan(cache: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"cache niet op te slaan: {e}")


def _meet(symbool: str) -> dict:
    """Brutomarge-trend en omzetgroei uit de kwartaalcijfers. Gooit bij geen data."""
    import yfinance as yf

    tk = yf.Ticker(symbool)
    inc = tk.quarterly_income_stmt
    if inc is None or getattr(inc, "empty", True):
        raise ValueError("geen kwartaalcijfers")

    kolommen = list(inc.columns)[:6]

    def cel(rij, kol):
        try:
            v = inc.loc[rij, kol]
            return None if v is None or v != v else float(v)
        except Exception:
            return None

    marges, omzetten = [], []
    for k in kolommen:
        omzet, bruto = cel("Total Revenue", k), cel("Gross Profit", k)
        omzetten.append(omzet)
        marges.append((bruto / omzet * 100) if (bruto is not None and omzet) else None)

    # Jaar-op-jaar vergelijken (index 4), niet drie kwartalen terug: brutomarges
    # kennen seizoenspatronen, en Q2 tegen Q3-van-vorig-jaar leggen meet het
    # seizoen in plaats van de trend. Valt index 4 weg, dan is de meting ONBEKEND
    # in plaats van dat we stilzwijgend op een kortere reeks overstappen.
    marge_nu = marges[0] if marges else None
    marge_toen = marges[4] if len(marges) > 4 else None
    marge_delta = (marge_nu - marge_toen) if (marge_nu is not None and marge_toen is not None) else None

    groei = None
    if len(omzetten) >= 5 and omzetten[0] and omzetten[4]:
        groei = (omzetten[0] / omzetten[4] - 1) * 100

    return {"brutomarge_pct": marge_nu, "marge_delta_pp": marge_delta,
            "omzetgroei_pct": groei}


def beoordeel(xyz_ticker: str, cache: dict = None) -> tuple:
    """(toegestaan, reden, meting). Dagelijks gecachet per ticker.

    toegestaan=False betekent: de fundamentals zakten mee, dit is geen
    sentiment-dip. Onmeetbaar geeft altijd True (zie fail-open hierboven).
    """
    symbool = _ticker(xyz_ticker)
    vandaag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eigen_cache = cache is None
    cache = _cache_laden() if eigen_cache else cache

    invoer = cache.get(symbool)
    if not invoer or invoer.get("datum") != vandaag:
        try:
            meting = _meet(symbool)
            invoer = {"datum": vandaag, "meting": meting, "fout": None}
        except Exception as e:
            invoer = {"datum": vandaag, "meting": None, "fout": str(e)[:100]}
        cache[symbool] = invoer
        if eigen_cache:
            _cache_opslaan(cache)

    meting = invoer.get("meting")
    if not meting:
        return True, "ONMEETBAAR (%s) — niet geblokkeerd" % (invoer.get("fout") or "geen data"), None

    delta, groei = meting.get("marge_delta_pp"), meting.get("omzetgroei_pct")

    if delta is not None and delta <= -MARGE_DALING_PP:
        return False, ("MARGE ZAKT MEE: brutomarge %+.1fpp over 4 kw — fundamenteel "
                       "bevestigde daling, geen sentiment" % delta), meting
    if groei is not None and groei < MIN_OMZETGROEI_PCT:
        return False, "OMZET KRIMPT: %+.1f%% jaar-op-jaar" % groei, meting

    stukken = []
    if delta is not None:
        stukken.append("marge %+.1fpp" % delta)
    if groei is not None:
        stukken.append("omzet %+.1f%%" % groei)
    if not stukken:
        return True, "ONMEETBAAR (geen marge- of omzetreeks) — niet geblokkeerd", meting
    return True, "fundamentals intact (%s)" % " · ".join(stukken), meting


def handhaven() -> bool:
    """Blokkeert de filter echt, of kijkt hij alleen mee?

    Default FALSE = observatiemodus: de uitslag komt in het rapport en de logs,
    maar verandert geen enkele order. Zo is er eerst bewijs over wat hij zou
    hebben tegengehouden voordat hij dat daadwerkelijk doet — hetzelfde patroon
    als `revalidation_autopause_enabled` bij de directionele hertoetsing.
    """
    try:
        from utils.auto_params import AutoParams
        v = AutoParams().get_candidate_value("divergence_filter_enforced")
        if v is not None:
            return str(v).strip().lower() in ("true", "1", "yes", "on")
    except Exception:
        pass
    return False


POSITIES_BESTAND = "thematic_exposure_positions.json"


def evalueer() -> None:
    """Verdict naast uitkomst: had de filter mogen handhaven?

    Dit is de enige vraag die telt. Een filter bouwen is makkelijk; weten of hij
    geld verdient of kost, vergt deze vergelijking. Posities zonder stempel bij
    aankoop worden apart gerapporteerd — daar is het oordeel van vandaag over een
    aankoop van toen, en dat is zwakker bewijs.
    """
    try:
        with open(POSITIES_BESTAND, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as e:
        print("kan %s niet lezen: %s" % (POSITIES_BESTAND, e))
        return

    cache = _cache_laden()
    schoon, backfill, onbekend = [], [], []
    for t, p in (d.get("positions") or {}).items():
        cb = float(p.get("cost_basis_usd") or 0)
        cv = float(p.get("current_value_usd") or 0)
        dicht = str(p.get("status", "")).upper() == "CLOSED"
        # Gesloten posities vóór 2026-08-12 hebben geen eigen realized_pnl_usd —
        # dat werd alleen in de totaalpost geteld. Die tellen als ONBEKEND en niet
        # als nul, anders verdunnen ze het gemiddelde met verzonnen nullen.
        if dicht:
            r = p.get("realized_pnl_usd")
            if r is None:
                onbekend.append(t)
                continue
            pnl = float(r)
        else:
            pnl = cv - cb
        stempel = p.get("divergence_at_entry")
        if stempel and stempel.get("ok") is not None:
            schoon.append((t, stempel["ok"], pnl, dicht))
        else:
            ok, _reden, _ = beoordeel(t, cache)
            backfill.append((t, ok, pnl, dicht))
    _cache_opslaan(cache)

    def rapport(rijen, kop, waarschuwing=""):
        if not rijen:
            return
        print("\n%s" % kop)
        if waarschuwing:
            print("  %s" % waarschuwing)
        for t, ok, pnl, dicht in rijen:
            print("    %-12s filter=%-4s %-7s P&L %+7.2f" % (
                t, "KOOP" if ok else "BLOK", "gesloten" if dicht else "open", pnl))
        for vlag, naam in ((True, "KOOP"), (False, "BLOK")):
            groep = [r for r in rijen if r[1] is vlag]
            if groep:
                som = sum(r[2] for r in groep)
                print("  %-4s n=%d  totaal P&L %+7.2f  gemiddeld %+6.2f"
                      % (naam, len(groep), som, som / len(groep)))

    if onbekend:
        print("Zonder resultaat-registratie (gesloten voor 2026-08-12): %s"
              % ", ".join(onbekend))
        print("  Die tellen NIET mee — een ontbrekend resultaat is geen nul.\n")
    print("Divergentie-screen — verdict tegen uitkomst")
    print("=" * 62)
    rapport(schoon, "Met stempel bij aankoop (hard bewijs):")
    rapport(backfill, "Zonder stempel (achteraf gemeten — zwakker bewijs):",
            "let op: dit is het oordeel van VANDAAG over een aankoop van toen")

    n = len(schoon)
    print("\n" + "=" * 62)
    if n < 10:
        print("Nog %d posities met stempel nodig voor een uitspraak (nu %d)." % (10 - n, n))
        print("Handhaven op minder is de steekproef verwarren met de uitkomst.")
    else:
        blok = [r for r in schoon if r[1] is False]
        koop = [r for r in schoon if r[1] is True]
        gb = sum(r[2] for r in blok) / len(blok) if blok else 0.0
        gk = sum(r[2] for r in koop) / len(koop) if koop else 0.0
        print("Gemiddelde P&L — KOOP %+.2f versus BLOK %+.2f." % (gk, gb))
        print("Handhaven is te verdedigen zodra BLOK structureel slechter is dan KOOP.")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--evalueer" in sys.argv:
        evalueer()
    else:
        tickers = [a for a in sys.argv[1:] if not a.startswith("--")] or \
                  ["XYZ-MSFT", "XYZ-ORCL", "XYZ-NOW", "XYZ-NVDA", "XYZ-CRCL"]
        cache = _cache_laden()
        print("handhaven: %s\n" % ("JA" if handhaven() else "NEE (observatiemodus)"))
        for t in tickers:
            ok, reden, _ = beoordeel(t, cache)
            print("  %-12s %-6s %s" % (t, "KOOP" if ok else "BLOK", reden))
        _cache_opslaan(cache)
