"""Toetst fundamentele wacht- en terugkeervoorwaarden aan de kwartaalcijfers.

Het gat dat dit dicht: de tracker keek dagelijks naar koersen en nooit naar
fundamentals — terwijl het hele raamwerk stelt dat fundamentals beslissen. Van de
twintig namen hadden er acht een machine-leesbare trigger (een prijs); de rest
wachtte op dingen als "twee kwartalen omzetgroei >= 9%", in proza.

Regelvorm in ledger.json:

    "wait_fundamental": {
      "mode": "all",                       # of "any"
      "rules": [
        {"metric": "revenue_growth_yoy_pct", "op": ">=", "value": 9.0, "quarters": 2}
      ]
    }

Semantiek: de regel is vervuld als de laatste `quarters` kwartalen ELK aan
`metric op value` voldoen.

Belangrijk: een metriek die niet te berekenen is, geeft None — "onbekend", niet
"niet vervuld" en zeker niet "vervuld". Een voorwaarde die je niet kunt meten mag
nooit stilletjes als gehaald tellen; dat is precies de definitiefout waar de
rekencontroles in research/README.md voor bestaan.
"""

import warnings

warnings.filterwarnings("ignore")

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


def _cel(df, rij, kolom):
    """Eén waarde uit een yfinance-frame, of None als hij ontbreekt."""
    try:
        if df is None or rij not in df.index or kolom not in df.columns:
            return None
        v = df.loc[rij, kolom]
        return None if v is None or v != v else float(v)  # v != v vangt NaN
    except Exception:
        return None


def kwartaalmetrieken(ticker, aantal=8):
    """Metrieken per kwartaal, nieuwste eerst. Ontbrekende waarden worden None."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    try:
        inc = tk.quarterly_income_stmt
        cf = tk.quarterly_cashflow
    except Exception:
        return []
    if inc is None or getattr(inc, "empty", True):
        return []

    kolommen = list(inc.columns)
    uit = []
    for i, k in enumerate(kolommen[:aantal]):
        omzet = _cel(inc, "Total Revenue", k)
        bruto = _cel(inc, "Gross Profit", k)
        oper = _cel(inc, "Operating Income", k)
        eps = _cel(inc, "Diluted EPS", k)
        if eps is None:
            eps = _cel(inc, "Basic EPS", k)

        # Jaar-op-jaar is vier kwartalen terug — niet het vorige kwartaal.
        groei = None
        if i + 4 < len(kolommen) and omzet:
            vorig = _cel(inc, "Total Revenue", kolommen[i + 4])
            if vorig:
                groei = (omzet / vorig - 1) * 100

        fcf = _cel(cf, "Free Cash Flow", k)
        if fcf is None:
            ocf, capex = _cel(cf, "Operating Cash Flow", k), _cel(cf, "Capital Expenditure", k)
            if ocf is not None and capex is not None:
                fcf = ocf + capex  # capex staat negatief in het overzicht

        uit.append({
            "periode": k.strftime("%Y-%m") if hasattr(k, "strftime") else str(k)[:7],
            "revenue_usd": omzet,
            "revenue_growth_yoy_pct": groei,
            "gross_margin_pct": (bruto / omzet * 100) if (bruto is not None and omzet) else None,
            "operating_margin_pct": (oper / omzet * 100) if (oper is not None and omzet) else None,
            "operating_income_usd": oper,
            "eps": eps,
            "fcf_quarter_usd": fcf,
        })
    return uit


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

    Geeft (vervuld, regels) waarbij vervuld True/False/None is. None wint van
    False bij 'all': kun je een deelregel niet meten, dan weet je het niet.
    """
    if not voorwaarde or not voorwaarde.get("rules"):
        return None, []
    if metrieken is None:
        metrieken = kwartaalmetrieken(ticker)
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

    # `partial` betekent: deze regels vormen samen NIET de hele voorwaarde — er
    # hangt een EN-deel aan dat hier niet te meten is (guidance, een prijsdrempel
    # die elders wordt gecheckt). Dan mag "gehaald" nooit als groen doorgaan;
    # anders meldt het systeem een koopsignaal op de helft van het bewijs.
    if vervuld is True and voorwaarde.get("partial"):
        vervuld = "gedeeltelijk"
    return vervuld, uitkomsten
