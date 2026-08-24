# -*- coding: utf-8 -*-
"""Eerlijke naspeling van de dip-koper — mét portemonnee en plekken.

    python -m scripts.sleeve_harness            # 180 dagen
    python -m scripts.sleeve_harness --dagen 365

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

def _laad_data(dagen: int):
    """Dagkoersen per ticker + de XYZ100-reeks voor de circuit-breaker."""
    import time
    import pandas as pd
    from utils.sleeve_revalidation import _fetch_daily
    from agents.technical_analyst import _get_shared_exchange

    ex = _get_shared_exchange()
    with open(THEMES_BESTAND) as f:
        cfg = json.load(f)
    conf = {t: c for t, c in cfg.get("tickers", {}).items()
            if c.get("status") == "CONFIRMED" and c.get("real_symbol")}
    since = int(time.time() * 1000) - dagen * 24 * 3600 * 1000

    DATA = {}
    for t in conf:
        d = _fetch_daily(ex, t, since)
        if d and len(d) >= 25:
            DATA[t] = d
    if len(DATA) < 3:
        sys.exit("te weinig data (%d tickers) — draai dit in de container" % len(DATA))

    eq = _fetch_daily(ex, "XYZ-XYZ100", since)
    eqs = pd.Series(dict(sorted(eq.items()))) if eq else None
    return conf, cfg.get("themes", {}), DATA, eqs


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

def speel_na(all_days, per_dag, DATA, conf, *, beperkt: bool, budget: float):
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

    per_naam = budget / MAX_CONCURRENT_NAMES * TRANCHE_PCTS[1]

    kas = budget
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
            elif gain >= 100 and not p["s3"]:
                fractie, sport = SLEEVE_PROFIT_TRIM_FRACTION, "s3"
            elif gain >= 60 and not p["s2"]:
                fractie, sport = SLEEVE_PROFIT_TRIM_FRACTION, "s2"
            elif gain >= 30 and not p["s1"]:
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
            posities[t] = {"entry": prijs, "stuks": inleg / prijs, "inleg": inleg,
                           "opbrengst": 0.0, "piek_waarde": inleg, "piek_gain": 0.0,
                           "min_gain": 0.0, "s1": False, "s2": False, "s3": False}

    # ── afrekenen op de laatste dag ────────────────────────────────────
    ld = all_days[-1]
    open_waarde = 0.0
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
        "open_waarde": round(open_waarde, 2) if beperkt else None,
        "gemist_vol": gemist_vol,
        "gemist_kas": gemist_kas,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dagen", type=int, default=180)
    ap.add_argument("--budget", type=float, default=LIVE_BUDGET)
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING)
    from utils.thematic_exposure_lab import (
        ThematicExposureLab, MAX_CONCURRENT_NAMES, TRANCHE_PCTS)

    lab = ThematicExposureLab()
    conf, themes, DATA, eqs = _laad_data(args.dagen)
    all_days, per_dag = _signalen(lab, conf, themes, DATA, eqs)

    per_naam = args.budget / MAX_CONCURRENT_NAMES * TRANCHE_PCTS[1]
    print("Eerlijke naspeling van de dip-koper")
    print("=" * 66)
    print("%d tickers · %d handelsdagen · budget $%.0f · %d plekken · $%.2f per instap"
          % (len(DATA), len(all_days), args.budget, MAX_CONCURRENT_NAMES, per_naam))
    print()

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
