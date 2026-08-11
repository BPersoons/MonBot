"""Controleert de ledger en de tracker-logica. Draait in CI en lokaal.

    python research/test_ledger.py

Waarom dit bestaat: de ledger is de enige dataset die telt voor de zesmaandstoets,
en hij kan stil kapot. Dat is geen theorie — `_benchmark.ticker` stond op "TODO",
waardoor elke regel een lege benchmarkprijs had en de toets achteraf niet af te
rekenen was geweest. Niemand merkte dat, want alles zag er verder normaal uit.

Exit 0 = alles goed, exit 1 = ten minste een fout.
"""

import io
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import track  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

VERDICTS = {"KOOPBAAR", "VOLGEN", "AFVALLER"}
DIMENSIES = {"role_in_chain", "margin_and_direction", "competition",
             "scalability", "execution", "valuation"}
GELDIGE_SCORES = {1, 2, 3, 4, 5, None}

_fouten = []
_gecontroleerd = 0


def eis(conditie, boodschap):
    global _gecontroleerd
    _gecontroleerd += 1
    if not conditie:
        _fouten.append(boodschap)


# --------------------------------------------------------------------- ledger

def controleer_ledger():
    with io.open(os.path.join(HERE, "ledger.json"), encoding="utf-8") as fh:
        d = json.load(fh)

    bench = d.get("_benchmark", {})
    eis(bench.get("ticker") and bench["ticker"] != "TODO",
        "_benchmark.ticker is leeg of staat nog op TODO — de zesmaandstoets is dan "
        "niet af te rekenen")

    actief = [e for e in d["entries"] if not e.get("superseded_by")]
    tickers = [e["ticker"] for e in actief]
    eis(len(tickers) == len(set(tickers)),
        "dubbele actieve ticker(s): %s"
        % sorted({t for t in tickers if tickers.count(t) > 1}))

    for e in d["entries"]:
        t = e.get("ticker", "<zonder ticker>")
        superseded = bool(e.get("superseded_by"))

        for veld in ("ticker", "name", "scored_at", "verdict", "card"):
            eis(e.get(veld), "%s: veld '%s' ontbreekt of is leeg" % (t, veld))

        eis(e.get("verdict") in VERDICTS,
            "%s: verdict '%s' is geen geldige waarde %s" % (t, e.get("verdict"), sorted(VERDICTS)))

        try:
            datetime.strptime(e.get("scored_at", "")[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            eis(False, "%s: scored_at '%s' is geen YYYY-MM-DD" % (t, e.get("scored_at")))

        # Prijzen: zonder deze twee is de regel later niet af te rekenen.
        if not superseded:
            p, b = e.get("price_at_score"), e.get("benchmark_price_at_score")
            eis(isinstance(p, (int, float)) and p > 0,
                "%s: price_at_score ontbreekt of is <= 0 (%r)" % (t, p))
            eis(isinstance(b, (int, float)) and b > 0,
                "%s: benchmark_price_at_score ontbreekt of is <= 0 (%r)" % (t, b))

        # Scores: precies de zes dimensies, geldige waarden.
        scores = e.get("scores")
        eis(isinstance(scores, dict), "%s: scores ontbreekt" % t)
        if isinstance(scores, dict):
            eis(set(scores) == DIMENSIES,
                "%s: scores-sleutels wijken af — ontbreekt %s, onbekend %s"
                % (t, sorted(DIMENSIES - set(scores)), sorted(set(scores) - DIMENSIES)))
            for k, v in scores.items():
                eis(v in GELDIGE_SCORES,
                    "%s: score %s=%r valt buiten 1-5 of None" % (t, k, v))

        poorten = e.get("gates", {})
        for p in ("survival", "core_etf_overlap", "liquidity"):
            eis(p in poorten, "%s: poort '%s' ontbreekt" % (t, p))

        eis(e.get("deciding_number"),
            "%s: deciding_number ontbreekt — zonder beslissend getal is de "
            "tiebreak-regel niet toe te passen" % t)

        kaart = os.path.join(REPO, e.get("card", ""))
        eis(e.get("card") and os.path.exists(kaart),
            "%s: kaartbestand '%s' bestaat niet" % (t, e.get("card")))

        if superseded:
            continue

        # Verdict-specifieke eisen.
        if e["verdict"] == "VOLGEN":
            eis(e.get("wait_conditions"),
                "%s: VOLGEN zonder wachtvoorwaarde — README maakt die verplicht" % t)
        if e["verdict"] == "AFVALLER":
            eis(e.get("return_to_volgen_conditions") or e.get("thesis_break"),
                "%s: AFVALLER zonder terugkeer- of these-breuk-voorwaarden" % t)
        if e["verdict"] == "KOOPBAAR" and isinstance(scores, dict):
            eis(None not in scores.values(),
                "%s: KOOPBAAR met een onbeantwoorde dimensie ('?')" % t)
            eis(1 not in scores.values(),
                "%s: KOOPBAAR met een dimensie op 1" % t)
            eis((scores.get("valuation") or 0) >= 3,
                "%s: KOOPBAAR met waardering < 3" % t)

        # Prijs-trigger moet een getal zijn als hij er staat.
        wp = e.get("wait_price_below")
        if wp is not None:
            eis(isinstance(wp, (int, float)) and wp > 0,
                "%s: wait_price_below is geen positief getal (%r)" % (t, wp))
            eis(e.get("wait_price_note"),
                "%s: wait_price_below zonder wait_price_note — dan weet je bij een "
                "alarm niet welke voorwaarde raakte" % t)

    return d, actief


# ------------------------------------------------------------------- logica

def controleer_logica(actief):
    # avg_score moet None-dimensies overslaan, niet als 0 tellen.
    e = {"scores": {"a": 4, "b": None, "c": 2}}
    eis(track.avg_score(e) == 3.0,
        "avg_score telt None mee: kreeg %r, verwacht 3.0" % track.avg_score(e))
    eis(track.avg_score({"scores": {"a": None}}) is None,
        "avg_score geeft geen None terug als alles onbekend is")

    # days_since moet zowel 'YYYY-MM-DD' als langere ISO-strings aankunnen.
    vandaag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eis(track.days_since(vandaag) == 0,
        "days_since(vandaag) gaf %r in plaats van 0" % track.days_since(vandaag))
    eis(track.days_since(vandaag + "T12:00:00") == 0,
        "days_since faalt op een ISO-datum met tijd")

    # De trigger-vergelijking: raakt bij gelijk en eronder, niet erboven.
    # Een omgedraaide operator is de duurste stille fout die dit script kan vangen.
    for koers, drempel, verwacht in ((119.0, 120.0, True), (120.0, 120.0, True),
                                     (120.01, 120.0, False)):
        eis((koers <= drempel) is verwacht,
            "trigger-vergelijking klopt niet bij koers %s / drempel %s" % (koers, drempel))

    # live_entries mag geen superseded regels teruggeven.
    eis(all(not e.get("superseded_by") for e in actief),
        "live_entries geeft een superseded regel terug")


# ---------------------------------------------------------------------- main

if __name__ == "__main__":
    d, actief = controleer_ledger()
    controleer_logica(actief)

    print("Ledger: %d actieve regels, %d controles uitgevoerd."
          % (len(actief), _gecontroleerd))
    if _fouten:
        print("\n%d FOUT(EN):" % len(_fouten))
        for f in _fouten:
            print("  - %s" % f)
        sys.exit(1)
    print("Alles goed.")
