# -*- coding: utf-8 -*-
"""Eerlijke naspeling van de dip-koper — mét portemonnee en plekken.

    python -m scripts.sleeve_harness            # 180 dagen
    python -m scripts.sleeve_harness --dagen 365
    python -m scripts.sleeve_harness --dagen 365 --budget 1250   # zelfde cache
    python -m scripts.sleeve_harness --ververs                   # koersen verversen

WAAROM DIT BESTAAT
------------------
`utils/sleeve_revalidation.py` meet de edge en rapporteert "+5,66% per positie".
Dat getal hoort bij een systeem dat wij niet draaien. Twee aannames zitten erin
die in productie niet gelden:

  1. Onbeperkt geld. Elke positie is een fractie van 1,0; er is altijd budget.
  2. Onbeperkte plekken. Elk signaal wordt een positie.

Live is het budget $255 en zijn er zes plekken. Zit het vol, dan gaat een
signaal gewoon voorbij — je KUNT niet kopen. Deze opstelling speelt dat wel na:
één portemonnee, zes plekken, geld dat opraakt, posities die een plek bezet
houden tot ze sluiten.

Het verschil is niet academisch. Het oude +44%-ijkpunt van de hoofd-swarm werd
−153% zodra iemand de naspeling getrouw maakte (zie
docs/DIRECTIONAL_CORE_REDESIGN.md). Dezelfde soort aanname, dezelfde soort
verrassing.

DE MEETLAT DIE TELT
-------------------
Bij beperkt kapitaal is "gemiddeld rendement per positie" de verkeerde maatstaf:
hij vertelt je hoe goed je keuzes waren, niet wat je portefeuille deed. Zes
plekken bezet houden met een middelmatige naam kost je de goede die daarna
langskomt, en dat zie je alleen terug in het PORTEFEUILLE-rendement. Dit script
rapporteert allebei, juist om te laten zien hoe ver ze uit elkaar lopen.

Alle regels en drempels komen uit `utils/thematic_exposure_lab.py` — niets
hier hardgecodeerd, anders drijft de naspeling weg van de werkelijkheid.
"""

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("SleeveHarness")

THEMES_BESTAND = "config/thematic_exposure_themes.json"

# Het echte budget van de sleeve-wallet. DEFAULT_BUDGET_USD ($1.250) is GEEN
# geldige invoer hier -- juist dat verschil maakte de oude naspeling onbruikbaar.
LIVE_BUDGET = 255.0


# --------------------------------------------------------------------- data

def _laad_data(dagen: int, ververs: bool = False):
    """Dagkoersen per ticker + de XYZ100-reeks voor de circuit-breaker.

    MET CACHE, en dat is geen snelheidstruc maar een meetvereiste. De ophaal via
    ccxt is niet deterministisch: twee runs achter elkaar leverden 36 en 33
    tickers op, omdat losse fetches falen. Twee configuraties tegen elkaar
    afzetten op een verschillende dataset meet het verschil in de DATA, niet in
    de configuratie — precies het soort definitiefout waar dit project vaker in
    is gelopen.

    De cache wordt weggeschreven per `dagen`. Gebruik `--ververs` om opnieuw op
    te halen; doe dat NIET halverwege een vergelijking.
    """
    import time
    import pandas as pd
    from utils.sleeve_revalidation import _fetch_daily
    from agents.technical_analyst import _get_shared_exchange

    with open(THEMES_BESTAND) as f:
        cfg = json.load(f)
    conf = {t: c for t, c in cfg.get("tickers", {}).items()
            if c.get("status") == "CONFIRMED" and c.get("real_symbol")}

    kern = _cache_lezen(dagen) if not ververs else None
    if kern is None:
        ex = _get_shared_exchange()
        since = int(time.time() * 1000) - dagen * 24 * 3600 * 1000
        DATA = {}
        for t in conf:
            d = _fetch_daily(ex, t, since)
            if d and len(d) >= 25:
                DATA[t] = d
        eq = _fetch_daily(ex, "XYZ-XYZ100", since)
        kern = {"tickers": DATA, "xyz100": eq or {},
                "opgehaald_op": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _cache_schrijven(dagen, kern)
        print("Koersen opgehaald en gecachet (%d tickers)." % len(DATA))
    else:
        print("Koersen uit cache van %s (%d tickers) — gebruik --ververs om opnieuw op te halen."
              % (kern["opgehaald_op"], len(kern["tickers"])))

    DATA = kern["tickers"]
    if len(DATA) < 3:
        sys.exit("te weinig data (%d tickers) — draai dit in de container" % len(DATA))
    eq = kern["xyz100"]
    eqs = pd.Series(dict(sorted(eq.items()))) if eq else None
    return conf, cfg.get("themes", {}), DATA, eqs


def _cache_pad(dagen: int) -> str:
    return "sleeve_harness_cache_%dd.json" % dagen


def _cache_lezen(dagen: int):
    """JSON maakt van int-sleutels strings; die moeten terug, anders vergelijkt
    de dag-lus straks een string met een int en valt alles stil zonder fout."""
    try:
        with open(_cache_pad(dagen), encoding="utf-8") as fh:
            rauw = json.load(fh)
    except (IOError, ValueError):
        return None
    return {
        "opgehaald_op": rauw.get("opgehaald_op", "?"),
        "tickers": {t: {int(d): float(c) for d, c in reeks.items()}
                    for t, reeks in rauw.get("tickers", {}).items()},
        "xyz100": {int(d): float(c) for d, c in rauw.get("xyz100", {}).items()},
    }


def _cache_schrijven(dagen: int, kern: dict) -> None:
    try:
        with open(_cache_pad(dagen), "w", encoding="utf-8") as fh:
            json.dump(kern, fh)
    except IOError as e:
        logger.warning("cache niet weggeschreven: %s", e)



def _laad_aandelen(conf, vanaf: str, tot: str, ververs: bool = False):
    """Dezelfde namen, maar op ECHTE aandelenhistorie in plaats van HL-candles.

    Waarom dit bestaat: de sleeve is alleen ooit gemeten op een stijgende markt.
    De XYZ-synthetics op Hyperliquid bestaan pas ~9 maanden, dus er zit geen
    enkele bear in die data en die komt er ook niet — zie het blok hieronder
    over de bewaartermijn. De onderliggende waarden zijn gewone aandelen met
    zestien jaar geschiedenis, inclusief 2022 (-41%) en de COVID-crash.

    WAT DIT WEL EN NIET IS. Het is niet hetzelfde systeem: geen funding, geen
    HL-tarieven, geen perp-mechaniek, en de synthetic volgt zijn onderliggende
    waarde niet tot op de cent. Het beantwoordt één vraag, en die is genoeg voor
    een go/no-go op kapitaal: overleeft "koop de sectorbrede terugval" een echte
    dalende markt? Dat is een vraag over koersgedrag, en koersgedrag is precies
    wat hier beschikbaar is.

    LET OP DE RESOLUTIE. Er is alleen dagdata (yfinance geeft geen uurkoersen
    voor 2022). We weten uit de vorige ronde dat dagmeting meelopende stops
    STRUCTUREEL benadeelt en vaste doelen bevoordeelt. Deze test is voor de
    gedeployde regel dus een ONDERGRENS: haalt hij het hier, dan is dat sterker
    bewijs, niet zwakker. Vergelijk deze cijfers nooit direct met de uurcijfers
    uit de HL-meting.
    """
    import pandas as pd
    pad = "sleeve_harness_aandelen_%s_%s.json" % (vanaf, tot)
    if not ververs:
        try:
            with open(pad, encoding="utf-8") as fh:
                rauw = json.load(fh)
            print("Aandelenkoersen uit cache (%d namen)." % len(rauw["tickers"]))
            DATA = {t: {int(k): float(v) for k, v in r.items()}
                    for t, r in rauw["tickers"].items()}
            eq = {int(k): float(v) for k, v in rauw["index"].items()}
            return DATA, (pd.Series(dict(sorted(eq.items()))) if eq else None)
        except (IOError, ValueError, KeyError):
            pass

    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf

    symbolen = {t: c["real_symbol"] for t, c in conf.items() if c.get("real_symbol")}
    ruw = yf.download(list(symbolen.values()) + ["^NDX"], start=vanaf, end=tot,
                      progress=False, auto_adjust=True)["Close"]

    def _reeks(kolom):
        s = ruw[kolom].dropna()
        return {int(ts.timestamp() * 1000) // 86400000: float(v) for ts, v in s.items()}

    DATA = {}
    for xyz, echt in symbolen.items():
        if echt not in ruw.columns:
            continue
        d = _reeks(echt)
        # Zelfde ondergrens als de HL-kant: minder dan 25 dagen is geen reeks.
        if len(d) >= 25:
            DATA[xyz] = d
    eq = _reeks("^NDX") if "^NDX" in ruw.columns else {}

    try:
        with open(pad, "w", encoding="utf-8") as fh:
            json.dump({"tickers": DATA, "index": eq}, fh)
    except IOError:
        pass
    print("Aandelenkoersen opgehaald (%d van %d namen, %s t/m %s)."
          % (len(DATA), len(symbolen), vanaf, tot))
    return DATA, (pd.Series(dict(sorted(eq.items()))) if eq else None)


# ── Waarom UUR en niet fijner (gemeten 2026-08-25) ────────────────────────
# Voor de hand liggende volgende stap: 5 minuten, want zo vaak kijkt productie.
# Dat kan niet, en het gaat ook nooit kunnen. Hyperliquid bewaart per
# tijdsinterval ongeveer 5000 candles en niet meer -- de vroegste beschikbare
# candle is dezelfde of je nu limit=200 of limit=5000 vraagt, en een expliciet
# venster verder terug geeft leeg terug:
#
#     5m  -> 17 dagen        15m -> 52 dagen
#     1h  -> 208 dagen       1d  -> 279 dagen
#
# Een venster van 180 dagen is dus alleen op UURbasis te meten. Uur is hier
# geen keuze maar het plafond.
#
# Tweede, onafhankelijke blokkade: over 60 dagen sluit deze strategie ~1
# positie (6 van de 7 staan aan het eind nog open). Een vergelijking op een
# venster van 52 dagen -- het maximum voor 15m -- wordt dus beslist door een
# of twee trades. Dat meet padgeluk, geen exit-regel.
def _fetch_uur(ex, sym, since_ms):
    """Uurcandles. Sleutel is het uur-stempel, niet de dag."""
    import time
    hl = sym + "/USDC:USDC"
    out, cur = [], since_ms
    for _ in range(30):
        try:
            b = ex.fetch_ohlcv(hl, "1h", since=cur, limit=5000)
        except Exception:
            return None
        if not b:
            break
        out += b
        if len(b) < 2:
            break
        cur = b[-1][0] + 1
        time.sleep(0.1)
    if not out:
        return None
    return {int(r[0]): float(r[4]) for r in out}


def _laad_uur(conf, dagen: int, ververs: bool = False):
    """Uurreeksen, apart gecachet. Alleen voor de UITSTAP-controle -- de
    instapsignalen blijven op dagkoersen, want zo rekent _pullback_score en
    zo werkt de live-pijplijn ook."""
    import time
    from agents.technical_analyst import _get_shared_exchange
    pad = "sleeve_harness_uur_%dd.json" % dagen
    if not ververs:
        try:
            with open(pad, encoding="utf-8") as fh:
                rauw = json.load(fh)
            print("Uurkoersen uit cache (%d tickers)." % len(rauw))
            return {t: {int(k): float(v) for k, v in r.items()} for t, r in rauw.items()}
        except (IOError, ValueError):
            pass
    ex = _get_shared_exchange()
    since = int(time.time() * 1000) - dagen * 24 * 3600 * 1000
    UUR = {}
    for t in conf:
        d = _fetch_uur(ex, t, since)
        if d and len(d) >= 100:
            UUR[t] = d
    try:
        with open(pad, "w", encoding="utf-8") as fh:
            json.dump(UUR, fh)
    except IOError:
        pass
    print("Uurkoersen opgehaald en gecachet (%d tickers)." % len(UUR))
    return UUR

def _signalen(lab, conf, themes, DATA, eqs):
    """Scores, breadth en circuit-breaker per dag. Eén keer rekenen, twee keer
    gebruiken — zo verschillen de twee modellen GARANDEERD alleen in kapitaal."""
    from utils.thematic_exposure_lab import (
        PULLBACK_VOL_THRESHOLD, SLEEVE_CIRCUIT_BREAKER_DD_PCT)

    roll_high = eqs.rolling(60, min_periods=20).max() if eqs is not None else None
    all_days = sorted(set().union(*[set(v.keys()) for v in DATA.values()]))
    theme_members = {th: [t for t in DATA if th in (conf[t].get("themes") or {})]
                     for th in themes}
    hist = {t: sorted(v.items()) for t, v in DATA.items()}

    per_dag = {}
    for day in all_days:
        cb_on = False
        if roll_high is not None and day in roll_high.index and roll_high[day] > 0:
            cb_on = ((roll_high[day] - eqs[day]) / roll_high[day] * 100) >= SLEEVE_CIRCUIT_BREAKER_DD_PCT
        sc = {}
        for t in DATA:
            cl = [c for d, c in hist[t] if d <= day]
            if len(cl) < 20 or day not in DATA[t]:
                continue
            sc[t] = lab._pullback_score(cl[:-1], cl[-1])
        breadth = {}
        for th, mem in theme_members.items():
            scr = [t for t in mem if t in sc]
            breadth[th] = (sum(1 for t in scr if sc[t]["pullback_z"] >= PULLBACK_VOL_THRESHOLD)
                           / len(scr)) if scr else 0.0
        per_dag[day] = {"cb": cb_on, "scores": sc, "breadth": breadth}
    return all_days, per_dag


# ---------------------------------------------------------------- naspeling

def speel_na(all_days, per_dag, DATA, conf, *, beperkt: bool, budget: float,
             variant: dict = None, vanaf: int = 0, kosten_pct: float = 0.0,
             UUR: dict = None, uren_per_dag: dict = None):
    """Speelt de sleeve na over de reeks.

    beperkt=False  → het huidige model: onbeperkt geld en plekken.
    beperkt=True   → de werkelijkheid: één portemonnee, zes plekken.

    De exit-regels zijn in BEIDE gevallen identiek en komen uit de live-module,
    zodat het verschil in uitkomst alleen door kapitaal kan komen.
    """
    from utils.thematic_exposure_lab import (
        PULLBACK_VOL_THRESHOLD, BREADTH_THRESHOLD, MAX_CONCURRENT_NAMES,
        TRANCHE_PCTS, SLEEVE_MAX_DRAWDOWN_STOP_PCT, SLEEVE_MIN_TRIM_NOTIONAL_USD,
        SLEEVE_PROFIT_TRIM_FRACTION, _trail_fraction)

    variant = variant or {}
    z_uit = variant.get("z_uit")            # uitstap als de daling is uitgewerkt
    max_dagen = variant.get("max_dagen")    # uitstap na zoveel dagen
    eerste_sport = variant.get("eerste_sport", 30.0)
    winst_uit = variant.get("winst_uit")    # VOLLEDIG eruit op een vast winstdoel
    # Meelopende winstbescherming: vanaf `trail_start` winst schuift de
    # uitstap mee op `trail_gap` procentpunt onder de hoogste stand. Anders
    # dan de bestaande NAV-trailing-stop, die in PROCENT VAN DE PIEKWAARDE
    # rekent (-20%) -- dit rekent in procentPUNTEN winst, en is dus veel
    # strakker: op +7% winst staat de uitstap op +6%, niet op +5,6%.
    trail_start = variant.get("trail_start")
    trail_gap = variant.get("trail_gap", 1.0)

    per_naam = budget / MAX_CONCURRENT_NAMES * TRANCHE_PCTS[1]

    kas = budget
    instap_namen = []
    duur_dicht, duur_open = [], []
    gerealiseerd = 0.0      # winst/verlies uit VOLLEDIG gesloten posities
    posities = {}
    gesloten = []          # rendement per positie (fractie)
    gemist_vol, gemist_kas = 0, 0

    for day in all_days[vanaf:]:
        dag = per_dag[day]
        sc = dag["scores"]

        # ── beheer bestaande posities ───────────────────────────────────
        # Op UURBASIS als die data er is. De live-sleeve controleert exits elke
        # ~5 minuten op de markprijs, niet één keer per dag op de slotkoers, en
        # dat verschil is niet neutraal: een winstdoel dat intraday geraakt
        # wordt maar niet standhoudt tot de close, mist de dag-naspeling
        # volledig. Alleen de EXITS gaan fijner -- de instapsignalen blijven
        # dagelijks, want zo rekent _pullback_score en zo werkt de live-pijplijn.
        stempels = (uren_per_dag.get(day) or []) if UUR else [None]
        for stempel in stempels:
            for t in list(posities):
                mark = (UUR.get(t, {}).get(stempel) if stempel is not None
                        else DATA[t].get(day))
                if mark is None:
                    continue
                p = posities[t]
                waarde = p["stuks"] * mark
                gain = (mark - p["entry"]) / p["entry"] * 100
                p["piek_waarde"] = max(p["piek_waarde"], waarde)
                p["piek_gain"] = max(p["piek_gain"], gain)
                p["min_gain"] = min(p["min_gain"], gain)
                trail = _trail_fraction(p["piek_gain"])

                fractie, sport = 0.0, None
                if gain <= -SLEEVE_MAX_DRAWDOWN_STOP_PCT:
                    fractie = 1.0
                elif (trail_start is not None and p["piek_gain"] >= trail_start
                      and gain <= p["piek_gain"] - trail_gap):
                    fractie = 1.0        # meegelopen winst teruggevallen: eruit
                elif winst_uit is not None and gain >= winst_uit:
                    fractie = 1.0        # vast winstdoel gehaald: hele positie eruit
                elif z_uit is not None and sc.get(t, {}).get("pullback_z", 99) < z_uit:
                    fractie = 1.0        # de daling is uitgewerkt: these afgerond
                elif max_dagen is not None and (day - p["dag_in"]) >= max_dagen:
                    fractie = 1.0        # te lang vast, ongeacht de stand
                elif gain >= 100 and not p["s3"]:
                    fractie, sport = SLEEVE_PROFIT_TRIM_FRACTION, "s3"
                elif gain >= 60 and not p["s2"]:
                    fractie, sport = SLEEVE_PROFIT_TRIM_FRACTION, "s2"
                elif gain >= eerste_sport and not p["s1"]:
                    fractie, sport = SLEEVE_PROFIT_TRIM_FRACTION, "s1"
                elif gain > 0 and waarde < p["piek_waarde"] * trail:
                    fractie = 1.0

                # Te kleine winnaar → helemaal dicht (regel van 2026-08-24).
                # Alleen in het beperkte model: de $10-vloer is een BEDRAG, en in
                # het fractie-model is de inleg 1,0 'eenheid'. Zou je hem daar ook
                # toepassen, dan werd élke winst-sport een volledige sluiting en
                # verschilden de modellen door eenheden in plaats van door kapitaal.
                if beperkt and sport and waarde * fractie < SLEEVE_MIN_TRIM_NOTIONAL_USD:
                    fractie, sport = 1.0, None

                if fractie <= 0:
                    continue
                if beperkt and fractie < 1.0 and waarde * fractie < SLEEVE_MIN_TRIM_NOTIONAL_USD:
                    continue                                   # order zou falen

                stuks_weg = p["stuks"] * fractie
                kas += stuks_weg * mark * (1 - kosten_pct / 100.0)   # verkoopkosten
                p["opbrengst"] += stuks_weg * mark * (1 - kosten_pct / 100.0)
                p["stuks"] -= stuks_weg
                p["piek_waarde"] *= (1.0 - fractie)            # piek schaalt mee
                if sport:
                    p[sport] = True
                if p["stuks"] <= 1e-9:
                    gesloten.append((p["opbrengst"] - p["inleg"]) / p["inleg"])
                    gerealiseerd += p["opbrengst"] - p["inleg"]
                    duur_dicht.append(day - p["dag_in"])
                    del posities[t]

        # ── nieuwe instap ───────────────────────────────────────────────
        if dag["cb"]:
            continue
        kandidaten = sorted(
            (t for t in sc
             if t not in posities
             and sc[t]["pullback_z"] >= PULLBACK_VOL_THRESHOLD
             and sc[t]["stabilized"]
             and max((dag["breadth"].get(th, 0.0)
                      for th in (conf[t].get("themes") or {})), default=0.0) >= BREADTH_THRESHOLD),
            key=lambda t: -sc[t]["pullback_z"],
        )
        if beperkt:
            kandidaten = kandidaten[:MAX_CONCURRENT_NAMES]

        for t in kandidaten:
            if day not in DATA[t]:
                continue
            if beperkt:
                if len(posities) >= MAX_CONCURRENT_NAMES:
                    gemist_vol += 1
                    continue
                if kas < per_naam:
                    gemist_kas += 1
                    continue
                inleg = per_naam
                kas -= inleg
                kas -= inleg * kosten_pct / 100.0        # instapkosten
            else:
                inleg = 1.0                                # fractie-model
            prijs = DATA[t][day]
            instap_namen.append(t)
            posities[t] = {"dag_in": day, "entry": prijs, "stuks": inleg / prijs, "inleg": inleg,
                           "opbrengst": -inleg * kosten_pct / 100.0,
                           "piek_waarde": inleg, "piek_gain": 0.0,
                           "min_gain": 0.0, "s1": False, "s2": False, "s3": False}

    # ── afrekenen op de laatste dag ────────────────────────────────────
    ld = all_days[-1]
    open_waarde = 0.0
    for p in posities.values():
        duur_open.append(ld - p["dag_in"])
    for t, p in posities.items():
        m = DATA[t].get(ld) or sorted(DATA[t].items())[-1][1]
        p["opbrengst"] += p["stuks"] * m * (1 - kosten_pct / 100.0)
        open_waarde += p["stuks"] * m
        gesloten.append((p["opbrengst"] - p["inleg"]) / p["inleg"])

    n = len(gesloten)
    return {
        "n": n,
        "win_rate": round(sum(1 for x in gesloten if x > 0) / n * 100, 1) if n else 0.0,
        "gem_per_positie_pct": round(sum(gesloten) / n * 100, 2) if n else 0.0,
        "portefeuille_pct": round((kas + open_waarde - budget) / budget * 100, 2) if beperkt else None,
        "eind_kas": round(kas, 2) if beperkt else None,
        "gerealiseerd": round(gerealiseerd, 2) if beperkt else None,
        "op_papier": round(kas + open_waarde - budget - gerealiseerd, 2) if beperkt else None,
        "n_gesloten": n - len(posities),
        "instap_namen": instap_namen,
        "duur_dicht": sorted(duur_dicht),
        "duur_open": sorted(duur_open),
        "open_waarde": round(open_waarde, 2) if beperkt else None,
        "gemist_vol": gemist_vol,
        "gemist_kas": gemist_kas,
    }



VARIANTEN = [
    ("huidig",              {}),
    ("vast uit op +5%",     {"winst_uit": 5.0}),
    ("vast uit op +6%",     {"winst_uit": 6.0}),
    ("vast uit op +8%",     {"winst_uit": 8.0}),
    ("meelopend 6% / 1pp",  {"trail_start": 6.0, "trail_gap": 1.0}),
    ("meelopend 6% / 2pp",  {"trail_start": 6.0, "trail_gap": 2.0}),
    ("meelopend 6% / 3pp",  {"trail_start": 6.0, "trail_gap": 3.0}),
    ("meelopend 5% / 1pp",  {"trail_start": 5.0, "trail_gap": 1.0}),
    ("meelopend 8% / 2pp",  {"trail_start": 8.0, "trail_gap": 2.0}),
    ("meelopend 10% / 3pp", {"trail_start": 10.0, "trail_gap": 3.0}),
    ("meelopend 15% / 5pp", {"trail_start": 15.0, "trail_gap": 5.0}),
]


def vergelijk(all_days, per_dag, DATA, conf, budget):
    """Alle uitstap-varianten tegen DEZELFDE data en dezelfde signalen.

    Beoordeel op GEREALISEERD, niet op portefeuille: dat laatste bevat
    marktwaarde van posities die nog open staan, en juist het uitstappen is
    wat we hier vergelijken. Een variant die alles vasthoudt scoort op
    portefeuille-rendement goed en heeft nog niets bewezen."""
    print()
    print("Uitstap-varianten, zelfde data en zelfde signalen")
    print("=" * 78)
    print("%-22s %11s %11s %9s %8s %9s" % (
        "", "portef.", "GEREAL.", "nog open", "instap", "med.duur"))
    print("-" * 78)
    for naam, opties in VARIANTEN:
        r = speel_na(all_days, per_dag, DATA, conf, beperkt=True,
                     budget=budget, variant=opties)
        do = r["duur_open"]
        dd = r["duur_dicht"]
        print("%-22s %10.2f%% %10s %9s %8d %9s" % (
            naam, r["portefeuille_pct"], "$%+.2f" % r["gerealiseerd"],
            "%d van %d" % (r["n"] - r["n_gesloten"], r["n"]), r["n"],
            "%d d" % (dd[len(dd)//2] if dd else 0)))
    print("-" * 78)
    print("GEREAL. = winst die echt geboekt is. 'nog open' = posities die aan het",
          "eind nooit zijn uitgestapt.")


def verdeling(all_days, per_dag, DATA, conf, budget, n_vensters=12, kosten_pct=0.0,
              UUR=None, uren_per_dag=None):
    """Elke variant over VEEL startmomenten, en dan de spreiding tonen.

    Een venster zegt niets: dezelfde regel gaf -$9,01 over 365 dagen en
    +$100,84 over 180. Dat is geen effect maar padgeluk -- met zes plekken
    bepaalt wie de plekken als eerste vult de hele rest van de reeks. Door
    dezelfde regel op verschoven startdagen te draaien wordt zichtbaar of een
    verschil de ruis overleeft. Zo niet, dan is de eerlijke uitkomst "niet te
    meten" -- en niet het beste getal uit de rij.
    """
    stap = max(1, (len(all_days) - 60) // n_vensters)
    starts = list(range(0, len(all_days) - 60, stap))[:n_vensters]
    print()
    print("Elke variant over %d startmomenten · kosten %.3f%% per kant"
          % (len(starts), kosten_pct))
    print("=" * 78)
    print("%-22s %10s %10s %10s %11s %8s" % (
        "", "mediaan", "slechtste", "beste", "spreiding", "> 0"))
    print("-" * 78)
    for naam, opties in VARIANTEN:
        uit = []
        for st in starts:
            r = speel_na(all_days, per_dag, DATA, conf, beperkt=True,
                         budget=budget, variant=opties, vanaf=st,
                         kosten_pct=kosten_pct, UUR=UUR, uren_per_dag=uren_per_dag)
            uit.append(r["gerealiseerd"])
        uit.sort()
        print("%-22s %10s %10s %10s %11s %7d/%d" % (
            naam, "$%+.2f" % uit[len(uit) // 2], "$%+.2f" % uit[0],
            "$%+.2f" % uit[-1], "$%.2f" % (uit[-1] - uit[0]),
            sum(1 for x in uit if x > 0), len(uit)))
    print("-" * 78)
    print("Alles GEREALISEERD. Is de spreiding groter dan het verschil tussen de")
    print("regels, dan meet je het venster en niet de regel.")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=180)
    ap.add_argument("--budget", type=float, default=LIVE_BUDGET)
    ap.add_argument("--uur", action="store_true",
                    help="exits op UURbasis controleren i.p.v. op de dagslotkoers")
    ap.add_argument("--kosten", type=float, default=0.0,
                    help="handelskosten in %% per kant (HL taker ~0,045)")
    ap.add_argument("--verdeling", action="store_true",
                    help="elke variant over veel startmomenten")
    ap.add_argument("--varianten", action="store_true",
                    help="vergelijk de uitstap-varianten i.p.v. de standaardrun")
    ap.add_argument("--ververs", action="store_true",
                    help="koersen opnieuw ophalen i.p.v. de cache gebruiken")
    ap.add_argument("--aandelen", action="store_true",
                    help="draai op ECHTE aandelenhistorie (yfinance) i.p.v. HL-candles "
                         "— de enige manier om een dalende markt te meten")
    ap.add_argument("--vanaf", default="2010-01-01",
                    help="startdatum bij --aandelen (JJJJ-MM-DD)")
    ap.add_argument("--tot", default="2026-08-25",
                    help="einddatum bij --aandelen (JJJJ-MM-DD)")
    args = ap.parse_args()

    if args.uur and args.aandelen:
        sys.exit("--uur werkt niet met --aandelen: yfinance geeft geen uurkoersen "
                 "voor oude vensters. Zie de toelichting bij _laad_aandelen.")

    logging.basicConfig(level=logging.WARNING)
    from utils.thematic_exposure_lab import (
        ThematicExposureLab, MAX_CONCURRENT_NAMES, TRANCHE_PCTS)

    lab = ThematicExposureLab()
    # De config (namen, thema's, drempels) is in beide modi dezelfde; alleen de
    # KOERSEN komen ergens anders vandaan. Zo verschillen de twee runs
    # gegarandeerd in de data en niet in de regels.
    conf, themes, DATA, eqs = _laad_data(args.dagen, ververs=args.ververs)
    if args.aandelen:
        DATA, eqs = _laad_aandelen(conf, args.vanaf, args.tot, ververs=args.ververs)
        if len(DATA) < 3:
            sys.exit("te weinig aandelenreeksen (%d)" % len(DATA))
    all_days, per_dag = _signalen(lab, conf, themes, DATA, eqs)

    per_naam = args.budget / MAX_CONCURRENT_NAMES * TRANCHE_PCTS[1]
    print("Eerlijke naspeling van de dip-koper")
    if args.aandelen:
        print("BRON: echte aandelenhistorie %s t/m %s — exits op DAGkoersen "
              "(ondergrens voor meelopers)" % (args.vanaf, args.tot))
    print("=" * 66)
    print("%d tickers · %d handelsdagen · budget $%.0f · %d plekken · $%.2f per instap"
          % (len(DATA), len(all_days), args.budget, MAX_CONCURRENT_NAMES, per_naam))
    print()

    UUR, uren_per_dag = None, None
    if args.uur:
        UUR = _laad_uur(conf, args.dagen, ververs=args.ververs)
        # elk uur-stempel bij zijn dag: de exits lopen per uur, de instap
        # blijft eens per dag op dezelfde signalen als hiervoor.
        uren_per_dag = {}
        for reeks in UUR.values():
            for ts in reeks:
                uren_per_dag.setdefault(ts // 86400000, set()).add(ts)
        uren_per_dag = {d: sorted(v) for d, v in uren_per_dag.items()}
        print("Uurdata: %d dagen met gemiddeld %.1f controles per dag."
              % (len(uren_per_dag),
                 sum(len(v) for v in uren_per_dag.values()) / max(len(uren_per_dag), 1)))

    if args.verdeling:
        verdeling(all_days, per_dag, DATA, conf, args.budget,
                  kosten_pct=args.kosten, UUR=UUR, uren_per_dag=uren_per_dag)
        return 0

    if args.varianten:
        vergelijk(all_days, per_dag, DATA, conf, args.budget)
        return 0

    vrij = speel_na(all_days, per_dag, DATA, conf, beperkt=False, budget=args.budget)
    echt = speel_na(all_days, per_dag, DATA, conf, beperkt=True, budget=args.budget)

    print("%-34s %14s %14s" % ("", "ONBEPERKT", "ECHT"))
    print("%-34s %14s %14s" % ("", "(huidig model)", "($255, 6 plek)"))
    print("-" * 66)
    print("%-34s %14d %14d" % ("instappen", vrij["n"], echt["n"]))
    print("%-34s %13.1f%% %13.1f%%" % ("treffers", vrij["win_rate"], echt["win_rate"]))
    print("%-34s %13.2f%% %13.2f%%" % ("gemiddeld per positie",
                                       vrij["gem_per_positie_pct"], echt["gem_per_positie_pct"]))
    print("-" * 66)
    print("%-34s %14s %13.2f%%" % ("PORTEFEUILLE-rendement", "n.v.t.", echt["portefeuille_pct"]))
    print("%-34s %14s %14s" % ("  waarvan kas", "", "$%.2f" % echt["eind_kas"]))
    print("%-34s %14s %14s" % ("  waarvan open posities", "", "$%.2f" % echt["open_waarde"]))
    print()
    print("Hoe hard is dat rendement?")
    print("  %-30s %14s   (%d posities echt gesloten)"
          % ("gerealiseerd", "$%+.2f" % echt["gerealiseerd"], echt["n_gesloten"]))
    print("  %-30s %14s   (%d posities nog open, marktwaarde)"
          % ("nog op papier", "$%+.2f" % echt["op_papier"], echt["n"] - echt["n_gesloten"]))
    print()
    print()
    print("Hoe lang zit hij ergens in? (kalenderdagen)")
    dd, do = echt["duur_dicht"], echt["duur_open"]
    if dd:
        print("  gesloten            n=%-3d  mediaan %3d   langste %3d"
              % (len(dd), dd[len(dd)//2], dd[-1]))
    if do:
        print("  NOG open            n=%-3d  mediaan %3d   langste %3d   <-- nooit uitgestapt"
              % (len(do), do[len(do)//2], do[-1]))
    print()
    print("Welke namen werden gekocht (in volgorde):")
    print("  " + ", ".join(echt["instap_namen"]))
    print()
    print("Signalen die NIET gekocht konden worden:")
    print("  %5d x geen plek vrij" % echt["gemist_vol"])
    print("  %5d x te weinig kas" % echt["gemist_kas"])
    print()
    print("=" * 66)
    print("'Gemiddeld per positie' is bij beperkt kapitaal de verkeerde maatstaf:")
    print("hij meet de kwaliteit van je keuzes, niet wat je portefeuille deed.")
    print("Het portefeuille-rendement is het getal waarop je alloceert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
