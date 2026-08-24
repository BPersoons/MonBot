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
    eis(bench.get("currency"),
        "_benchmark.currency ontbreekt — zonder valuta weet de tracker niet of hij "
        "moet omrekenen, en dan meet je een EUR/USD-beweging als selectie-edge")

    # De namen noteren in USD, de kern-ETF in EUR. Zodra die twee verschillen is
    # een wisselkoers verplicht, per regel en op de scoredatum vastgelegd.
    valutas = {e.get("currency") or "USD" for e in d["entries"]}
    if valutas - {bench.get("currency")}:
        eis(bench.get("fx_ticker"),
            "_benchmark.fx_ticker ontbreekt terwijl er regels in een andere valuta "
            "(%s) staan dan de benchmark (%s)"
            % (sorted(valutas - {bench.get("currency")}), bench.get("currency")))
        eis(bench.get("fx_quote"),
            "_benchmark.fx_quote ontbreekt — zonder de noteringsrichting ('USD per "
            "EUR') is niet vast te stellen of er gedeeld of vermenigvuldigd moet "
            "worden, en een omgedraaid paar ziet er plausibel uit")

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

            # En de wisselkoers, zodra de regel in een andere valuta noteert dan
            # de benchmark. Ontbreekt hij, dan slaat de tracker de regel over --
            # stil uit de meting vallen is erger dan een luide fout hier.
            if (e.get("currency") or "USD") != bench.get("currency"):
                fx = e.get("fx_at_score")
                eis(isinstance(fx, (int, float)) and fx > 0,
                    "%s: fx_at_score ontbreekt of is <= 0 (%r) terwijl de regel in "
                    "%s noteert en de benchmark in %s"
                    % (t, fx, e.get("currency") or "USD", bench.get("currency")))

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

    # --- de valuta-omrekening ------------------------------------------------
    # Dit is de duurste stille fout in het hele grootboek: draai de wisselkoers om
    # en er komt nog steeds een plausibel getal uit, alleen de verkeerde kant op.
    # Daarom met de hand uitgerekende cijfers in plaats van een herhaling van de
    # formule. Naam: $100 -> $110. EURUSD 1,25 -> 1,00 (de dollar wordt sterker).
    # In euro's: 100/1,25 = EUR 80 -> 110/1,00 = EUR 110, dus +37,5%.
    bench_eur = {"ticker": "WEBN.DE", "label": "WEBN", "name": "kern",
                 "currency": "EUR", "fx_ticker": "EURUSD=X"}
    regel = {"price_at_score": 100.0, "benchmark_price_at_score": 10.0,
             "fx_at_score": 1.25, "currency": "USD"}
    naam, bm = track.returns_pct(regel, 110.0, 10.0, 1.00, bench_eur)
    eis(naam is not None and abs(naam - 37.5) < 1e-9,
        "returns_pct rekent de naam verkeerd om: kreeg %r, verwacht +37,5%% "
        "(een sterkere dollar MOET het euro-rendement verhogen)" % naam)
    eis(bm is not None and abs(bm) < 1e-9,
        "returns_pct geeft een benchmarkrendement van %r bij een vlakke benchmark" % bm)

    # Zelfde valuta: geen omrekening, ook niet als er een koers meegegeven wordt.
    zelfde = {"price_at_score": 100.0, "benchmark_price_at_score": 10.0,
              "fx_at_score": 1.25, "currency": "EUR"}
    naam, _ = track.returns_pct(zelfde, 110.0, 10.0, 1.00, bench_eur)
    eis(naam is not None and abs(naam - 10.0) < 1e-9,
        "returns_pct rekent om terwijl regel en benchmark dezelfde valuta hebben "
        "(kreeg %r, verwacht +10,0%%)" % naam)

    # Ontbrekend gegeven geeft None, nooit stil een getal.
    for ontbreekt, waarde in (("price_at_score", None), ("fx_at_score", None)):
        kapot = dict(regel)
        kapot[ontbreekt] = waarde
        naam, _ = track.returns_pct(kapot, 110.0, 10.0, 1.00, bench_eur)
        eis(naam is None,
            "returns_pct geeft een getal terug terwijl '%s' ontbreekt" % ontbreekt)
    naam, _ = track.returns_pct(regel, 110.0, 10.0, None, bench_eur)
    eis(naam is None,
        "returns_pct rekent door zonder actuele wisselkoers — dan landt de hele "
        "valutabeweging in het verschil naam-min-benchmark")

    # De struikeldraad tegen een omgedraaid valutapaar moet echt afbreken.
    entries_fx = [{"fx_at_score": 1.1546}]
    try:
        track._verify_fx(entries_fx, 1.1673, bench_eur)  # normale beweging: mag door
        ok_normaal = True
    except SystemExit:
        ok_normaal = False
    eis(ok_normaal, "_verify_fx breekt af op een normale koersbeweging (1,1546 -> 1,1673)")

    try:
        track._verify_fx(entries_fx, 1 / 1.1673, bench_eur)  # omgedraaid paar
        ok_omgedraaid = False
    except SystemExit:
        ok_omgedraaid = True
    eis(ok_omgedraaid,
        "_verify_fx laat een OMGEDRAAID valutapaar (0,857 i.p.v. 1,167) door — "
        "precies de fout die hij moet vangen")


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
