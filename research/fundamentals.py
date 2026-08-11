"""Toetst fundamentele wacht- en terugkeervoorwaarden aan de kwartaalcijfers.

Het gat dat dit dicht: de tracker keek dagelijks naar koersen en nooit naar
fundamentals — terwijl het hele raamwerk stelt dat fundamentals beslissen. Van de
twintig namen hadden er acht een machine-leesbare trigger (een prijs); de rest
wachtte op dingen als "twee kwartalen omzetgroei >= 9%", in proza.

Regelvorm in ledger.json:

    "wait_fundamental": {
      "mode": "all",                       # of "any"
      "partial": true,                     # optioneel: deze regels zijn maar EEN
                                           #   helft van de hele voorwaarde
      "rules": [
        {"metric": "revenue_growth_yoy_pct", "op": ">=", "value": 9.0, "quarters": 2}
      ]
    }

Semantiek: de regel is vervuld als de laatste `quarters` kwartalen ELK aan
`metric op value` voldoen.

Twee ontwerpregels die ertoe doen:

1. Een metriek die niet te berekenen is geeft None — "onbekend", niet "niet
   vervuld" en zeker niet "vervuld". Een voorwaarde die je niet kunt meten mag
   nooit stilletjes als gehaald tellen; dat is precies de definitiefout waar de
   rekencontroles in research/README.md voor bestaan.

2. `partial` betekent dat de gecodeerde regels samen NIET de hele voorwaarde
   vormen (er hangt een EN-deel aan dat hier niet meetbaar is). Dan wordt
   "gehaald" gedegradeerd tot "gedeeltelijk" — anders meldt het systeem een
   koopsignaal op de helft van het bewijs.

## Waarom we metrieken zelf bewaren

yfinance levert maar ~5 kwartalen. Jaar-op-jaar groei vergelijkt met vier
kwartalen terug, dus voor het op een na nieuwste kwartaal viel de vergelijking
vaak buiten het venster — 7 van de 16 namen kwamen daardoor op "onbekend" uit.
`metrics_history.json` bewaart de RUWE kwartaalwaarden bij elke run; de afgeleide
metrieken (marges, groei) worden berekend over de samengevoegde reeks. Daarmee
groeit de dekking vanzelf mee met de tijd in plaats van vast te zitten op wat de
bron toevallig teruggeeft.
"""

import io
import json
import os
import warnings

warnings.filterwarnings("ignore")

HISTORIE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metrics_history.json")

RUWE_VELDEN = ("revenue_usd", "gross_profit_usd", "operating_income_usd",
               "eps", "fcf_quarter_usd")

METRIEKEN = (
    "revenue_usd", "revenue_growth_yoy_pct", "gross_margin_pct",
    "operating_margin_pct", "operating_income_usd", "eps", "fcf_quarter_usd",
)

_OPS = {
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


# ------------------------------------------------------------------- historie

def laad_historie():
    if not os.path.exists(HISTORIE):
        return {}
    try:
        with io.open(HISTORIE, encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, IOError):
        return {}


def bewaar_historie(hist):
    with io.open(HISTORIE, "w", encoding="utf-8") as fh:
        json.dump(hist, fh, indent=2, ensure_ascii=False, sort_keys=True)


def _samenvoegen(oud, vers):
    """Verse waarden winnen; oude kwartalen blijven staan.

    Zo groeit de reeks voorbij het venster dat de bron teruggeeft, zonder dat een
    herziening in de bron genegeerd wordt.
    """
    samen = dict(oud or {})
    for periode, waarden in vers.items():
        bestaand = dict(samen.get(periode, {}))
        bestaand.update({k: v for k, v in waarden.items() if v is not None})
        samen[periode] = bestaand
    return samen


# ------------------------------------------------------------------ ophalen

def _cel(df, rij, kolom):
    """Eén waarde uit een yfinance-frame, of None als hij ontbreekt."""
    try:
        if df is None or rij not in df.index or kolom not in df.columns:
            return None
        v = df.loc[rij, kolom]
        return None if v is None or v != v else float(v)  # v != v vangt NaN
    except Exception:
        return None


def ruwe_kwartalen(ticker, aantal=8):
    """Ruwe kwartaalwaarden uit yfinance, als {periode: {veld: waarde}}."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    try:
        inc = tk.quarterly_income_stmt
        cf = tk.quarterly_cashflow
    except Exception:
        return {}
    if inc is None or getattr(inc, "empty", True):
        return {}

    uit = {}
    for k in list(inc.columns)[:aantal]:
        periode = k.strftime("%Y-%m") if hasattr(k, "strftime") else str(k)[:7]
        eps = _cel(inc, "Diluted EPS", k)
        if eps is None:
            eps = _cel(inc, "Basic EPS", k)
        fcf = _cel(cf, "Free Cash Flow", k)
        if fcf is None:
            ocf, capex = _cel(cf, "Operating Cash Flow", k), _cel(cf, "Capital Expenditure", k)
            if ocf is not None and capex is not None:
                fcf = ocf + capex  # capex staat negatief in het overzicht
        waarden = {
            "revenue_usd": _cel(inc, "Total Revenue", k),
            "gross_profit_usd": _cel(inc, "Gross Profit", k),
            "operating_income_usd": _cel(inc, "Operating Income", k),
            "eps": eps,
            "fcf_quarter_usd": fcf,
        }
        # yfinance geeft soms lege staartkolommen terug. Die opslaan suggereert
        # dekking die er niet is: de periode telt mee, maar elke afgeleide
        # metriek erop blijft onbekend.
        if any(v is not None for v in waarden.values()):
            uit[periode] = waarden
    return uit


def _kwartaal_index(periode):
    """'2026-06' -> 8106, zodat 'vier kwartalen terug' rekenkundig klopt."""
    jaar, maand = int(periode[:4]), int(periode[5:7])
    return jaar * 4 + (maand - 1) // 3


def bereken_metrieken(ruw):
    """Afgeleide metrieken over de samengevoegde reeks. Nieuwste eerst."""
    perioden = sorted(ruw, reverse=True)
    per_index = {_kwartaal_index(p): p for p in perioden}
    uit = []
    for p in perioden:
        w = ruw[p]
        omzet, bruto = w.get("revenue_usd"), w.get("gross_profit_usd")
        oper = w.get("operating_income_usd")

        groei = None
        vorig_p = per_index.get(_kwartaal_index(p) - 4)
        if vorig_p and omzet:
            vorig = ruw[vorig_p].get("revenue_usd")
            if vorig:
                groei = (omzet / vorig - 1) * 100

        uit.append({
            "periode": p,
            "revenue_usd": omzet,
            "revenue_growth_yoy_pct": groei,
            "gross_margin_pct": (bruto / omzet * 100) if (bruto is not None and omzet) else None,
            "operating_margin_pct": (oper / omzet * 100) if (oper is not None and omzet) else None,
            "operating_income_usd": oper,
            "eps": w.get("eps"),
            "fcf_quarter_usd": w.get("fcf_quarter_usd"),
        })
    return uit


def kwartaalmetrieken(ticker, historie=None, ververs=True):
    """Metrieken per kwartaal, nieuwste eerst, over bron + eigen historie."""
    hist = laad_historie() if historie is None else historie
    ruw = dict(hist.get(ticker, {}))
    if ververs:
        ruw = _samenvoegen(ruw, ruwe_kwartalen(ticker))
        hist[ticker] = ruw
    return bereken_metrieken(ruw), hist


# -------------------------------------------------------------------- toetsen

def toets_regel(metrieken, regel):
    """(vervuld, uitleg). vervuld is True / False / None(=onbekend)."""
    naam, op, drempel = regel.get("metric"), regel.get("op"), regel.get("value")
    n = int(regel.get("quarters", 1))

    if naam not in METRIEKEN:
        return None, "onbekende metriek '%s'" % naam
    if op not in _OPS:
        return None, "onbekende operator '%s'" % op
    if len(metrieken) < n:
        return None, "te weinig kwartalen beschikbaar (%d van %d)" % (len(metrieken), n)

    venster = metrieken[:n]
    waarden = [m.get(naam) for m in venster]
    if any(w is None for w in waarden):
        ontbreekt = [m["periode"] for m, w in zip(venster, waarden) if w is None]
        return None, "%s onbekend in %s" % (naam, ", ".join(ontbreekt))

    resultaten = [_OPS[op](w, drempel) for w in waarden]
    details = " · ".join("%s %.2f" % (m["periode"], w) for m, w in zip(venster, waarden))
    return all(resultaten), "%s %s %s over %d kw → %s" % (naam, op, drempel, n, details)


def toets_voorwaarde(ticker, voorwaarde, metrieken=None):
    """Toetst een heel wait_fundamental/return_fundamental-blok.

    Geeft (vervuld, regels). vervuld is True / False / None / "gedeeltelijk".
    """
    if not voorwaarde or not voorwaarde.get("rules"):
        return None, []
    if metrieken is None:
        metrieken, _ = kwartaalmetrieken(ticker)
    if not metrieken:
        return None, [(None, "geen kwartaalcijfers opgehaald")]

    uitkomsten = [toets_regel(metrieken, r) for r in voorwaarde["rules"]]
    vlaggen = [v for v, _ in uitkomsten]
    modus = voorwaarde.get("mode", "all")

    if modus == "any":
        if any(v is True for v in vlaggen):
            vervuld = True
        elif any(v is None for v in vlaggen):
            vervuld = None
        else:
            vervuld = False
    else:  # all
        if any(v is False for v in vlaggen):
            vervuld = False       # één harde nee is genoeg
        elif any(v is None for v in vlaggen):
            vervuld = None        # anders: onmeetbaar blijft onbekend
        else:
            vervuld = True

    if vervuld is True and voorwaarde.get("partial"):
        vervuld = "gedeeltelijk"
    return vervuld, uitkomsten
