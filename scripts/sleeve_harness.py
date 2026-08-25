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
             variant: dict = None):
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

    per_naam = budget / MAX_CONCURRENT_NAMES * TRANCHE_PCTS[1]

    kas = budget
    instap_namen = []
    duur_dicht, duur_open = [], []
    gerealiseerd = 0.0      # winst/verlies uit VOLLEDIG gesloten posities
    posities = {}
    gesloten = []          # rendement per positie (fractie)
    gemist_vol, gemist_kas = 0, 0

    for day in all_days:
        dag = per_dag[day]
        sc = dag["scores"]

        # ── beheer bestaande posities ───────────────────────────────────
        for t in list(posities):
            if day not in DATA[t]:
                continue
            p = posities[t]
            mark = DATA[t][day]
            waarde = p["stuks"] * mark
            gain = (mark - p["entry"]) / p["entry"] * 100
            p["piek_waarde"] = max(p["piek_waarde"], waarde)
            p["piek_gain"] = max(p["piek_gain"], gain)
            p["min_gain"] = min(p["min_gain"], gain)
            trail = _trail_fraction(p["piek_gain"])

            fractie, sport = 0.0, None
            if gain <= -SLEEVE_MAX_DRAWDOWN_STOP_PCT:
                fractie = 1.0
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
            kas += stuks_weg * mark
            p["opbrengst"] += stuks_weg * mark
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
            else:
                inleg = 1.0                                # fractie-model
            prijs = DATA[t][day]
            instap_namen.append(t)
            posities[t] = {"dag_in": day, "entry": prijs, "stuks": inleg / prijs, "inleg": inleg,
                           "opbrengst": 0.0, "piek_waarde": inleg, "piek_gain": 0.0,
                           "min_gain": 0.0, "s1": False, "s2": False, "s3": False}

    # ── afrekenen op de laatste dag ────────────────────────────────────
    ld = all_days[-1]
    open_waarde = 0.0
    for p in posities.values():
        duur_open.append(ld - p["dag_in"])
    for t, p in posities.items():
        m = DATA[t].get(ld) or sorted(DATA[t].items())[-1][1]
        p["opbrengst"] += p["stuks"] * m
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
    ("uit op signaal z<1.0", {"z_uit": 1.0}),
    ("uit op signaal z<0.5", {"z_uit": 0.5}),
    ("uit na 60 dagen",     {"max_dagen": 60}),
    ("uit na 90 dagen",     {"max_dagen": 90}),
    ("eerste sport +15%",   {"eerste_sport": 15.0}),
    ("eerste sport +20%",   {"eerste_sport": 20.0}),
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

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=180)
    ap.add_argument("--budget", type=float, default=LIVE_BUDGET)
    ap.add_argument("--varianten", action="store_true",
                    help="vergelijk de uitstap-varianten i.p.v. de standaardrun")
    ap.add_argument("--ververs", action="store_true",
                    help="koersen opnieuw ophalen i.p.v. de cache gebruiken")
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)
    from utils.thematic_exposure_lab import (
        ThematicExposureLab, MAX_CONCURRENT_NAMES, TRANCHE_PCTS)

    lab = ThematicExposureLab()
    conf, themes, DATA, eqs = _laad_data(args.dagen, ververs=args.ververs)
    all_days, per_dag = _signalen(lab, conf, themes, DATA, eqs)

    per_naam = args.budget / MAX_CONCURRENT_NAMES * TRANCHE_PCTS[1]
    print("Eerlijke naspeling van de dip-koper")
    print("=" * 66)
    print("%d tickers · %d handelsdagen · budget $%.0f · %d plekken · $%.2f per instap"
          % (len(DATA), len(all_days), args.budget, MAX_CONCURRENT_NAMES, per_naam))
    print()

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
