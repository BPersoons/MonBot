"""Schaduwpotjes — uitschieter- en schakelmandjes vooruit gemeten, zonder geld.

    python research/schaduwpotjes.py bijwerken   # na het slot: alle potjes een dag verder
    python research/schaduwpotjes.py stand       # stand per potje, niets schrijven

Waarom (docs/MOTOR.md spelregel 2b, ontwerpreview proeftuinmotor 22-09): een koop-en-houd-
these met vaste regels meet je vooruit op dagkoersen even goed als met geld, gratis en zoveel
tegelijk als er ideeën zijn. Pas als een schaduwpotje promotie verdient, komt er geld en een
geldmotor.

ELK POTJE HEEFT TWEE MAATSTAVEN (Bart 21-09: "de waarde zit in bepaalde schakels van de keten"):
- de KERN (WEBN) — is het beter dan wat je al hebt?
- het THEMAFONDS van hetzelfde thema — verslaat de schakel het thema als geheel?

REGELS per potje (config in research/schaduwpotjes.json, vastgelegd vóór de start):
- gelijke weging bij de start, gekocht op het eerste slot waarop ALLE namen een koers hebben
- stop: positie >= stop_verlies_pct onder de inleg -> verkopen op het slot
- winst laten lopen: pas vanaf laten_lopen_tot_winst_pct winst geldt een trailing stop van
  trailing_vanaf_top_pct onder de hoogste waarde van die positie
- oogst: is het potje (zonder de kern) meer dan oogst_boven_x keer de inleg waard, dan gaat het
  overschot pro rata naar de kern (virtuele WEBN-stukken); het telt mee in het resultaat
- kosten: vast per order (DeGiro) en/of een percentage (HL-taker); funding per jaar voor HL-perps
Alles in euro's (namen omgerekend met EURUSD / EURCHF), zoals de scorekaart.

Onmeetbaar is geen koers: een ontbrekende dagkoers wordt hooguit 5 handelsdagen doorgetrokken;
daarna staat het potje stil op die dag en meldt de uitvoer het (geen verzonnen waarde).
"""

import io
import json
import math
import os
import sys

STAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schaduwpotjes.json")
KERN = "WEBN.DE"
FX = {"USD": "EURUSD=X", "CHF": "EURCHF=X"}
MAX_DOORTREKKEN = 5


# ── de regels, los van data zodat ze toetsbaar zijn ────────────────────────────────────

def kosten(bedrag, regels):
    return float(regels.get("kosten_per_order_eur", 0.0)) + abs(bedrag) * float(regels.get("kosten_pct", 0.0)) / 100.0


def start(pot, prijzen, dag, kern_prijs):
    """Koop gelijk gewogen. `prijzen`: {naam: koers_eur}. Muteert en geeft het potje terug."""
    r = pot["regels"]
    namen = list(pot["instrumenten"])
    per_naam = float(pot["inleg_eur"]) / len(namen)
    pot["posities"], pot["kas_eur"] = {}, 0.0
    for n in namen:
        k = kosten(per_naam, r)
        stuks = (per_naam - k) / prijzen[n]
        pot["posities"][n] = {"stuks": stuks, "inleg_eur": per_naam, "top_eur": per_naam - k, "open": True,
                              "hoogste_winst_pct": 0.0}
    pot["gestart_op"], pot["laatste_dag"] = dag, dag
    pot["kern_stuks"] = 0.0
    pot["maatstaf_start"] = {"kern": kern_prijs}
    pot.setdefault("gebeurtenissen", [])
    return pot


def waarde(pot, prijzen, kern_prijs):
    open_w = sum(p["stuks"] * prijzen[n] for n, p in pot["posities"].items() if p["open"])
    return pot["kas_eur"] + open_w + pot.get("kern_stuks", 0.0) * kern_prijs


def verwerk_dag(pot, prijzen, dag, kern_prijs, dagen):
    """Eén handelsdag verder: funding, stops, trailing, oogst. `dagen` = kalenderdagen sinds de vorige."""
    r = pot["regels"]
    stop = float(r["stop_verlies_pct"])
    lopen = float(r["laten_lopen_tot_winst_pct"])
    trail = float(r["trailing_vanaf_top_pct"])
    for n, p in pot["posities"].items():
        if not p["open"]:
            continue
        w = p["stuks"] * prijzen[n]
        funding = w * float(r.get("funding_pct_per_jaar", 0.0)) / 100.0 * dagen / 365.0
        pot["kas_eur"] -= funding
        winst_pct = (w / p["inleg_eur"] - 1) * 100
        p["hoogste_winst_pct"] = max(p["hoogste_winst_pct"], winst_pct)
        p["top_eur"] = max(p["top_eur"], w)
        reden = None
        if winst_pct <= -stop:
            reden = "stop (%.1f%%)" % winst_pct
        elif p["hoogste_winst_pct"] >= lopen and w <= p["top_eur"] * (1 - trail / 100.0):
            reden = "trailing (%.1f%% onder de top, winst %.1f%%)" % ((w / p["top_eur"] - 1) * 100, winst_pct)
        if reden:
            pot["kas_eur"] += w - kosten(w, r)
            p["open"] = False
            p["gesloten_op"], p["gesloten_eur"] = dag, round(w, 4)
            pot["gebeurtenissen"].append({"dag": dag, "naam": n, "wat": reden})
    # oogst: overschot boven oogst_boven_x * inleg naar de kern
    x = float(r.get("oogst_boven_x", 0) or 0)
    if x > 0 and kern_prijs > 0:
        zonder_kern = waarde(pot, prijzen, kern_prijs) - pot.get("kern_stuks", 0.0) * kern_prijs
        grens = x * float(pot["inleg_eur"])
        if zonder_kern > grens:
            overschot = zonder_kern - grens
            uit_kas = min(pot["kas_eur"], overschot)
            pot["kas_eur"] -= uit_kas
            rest = overschot - uit_kas
            open_w = {n: p["stuks"] * prijzen[n] for n, p in pot["posities"].items() if p["open"]}
            totaal = sum(open_w.values())
            opbrengst = uit_kas
            if rest > 0 and totaal > 0:
                for n, w in open_w.items():
                    deel = rest * w / totaal
                    pot["posities"][n]["stuks"] -= deel / prijzen[n]
                    opbrengst += deel - kosten(deel, r)
            pot["kern_stuks"] = pot.get("kern_stuks", 0.0) + opbrengst / kern_prijs
            pot["gebeurtenissen"].append({"dag": dag, "naam": "*", "wat": "oogst EUR %.2f naar de kern" % opbrengst})
    pot["laatste_dag"] = dag
    return pot


# ── data ───────────────────────────────────────────────────────────────────────────────

def _laad():
    with io.open(STAND, encoding="utf-8") as fh:
        return json.load(fh)


def _schrijf(d):
    with io.open(STAND, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _koersen_eur(tickers_valuta, vanaf):
    """DataFrame dag x ticker in euro's (hooguit MAX_DOORTREKKEN dagen doorgetrokken)."""
    import pandas as pd
    import yfinance as yf
    from datetime import date, timedelta
    nodig = set(tickers_valuta) | {FX[v] for v in tickers_valuta.values() if v in FX}
    ruw = {}
    # 10 dagen eerder beginnen, zodat doortrekken ook op de startdag kan
    begin = (date.fromisoformat(vanaf) - timedelta(days=10)).isoformat()
    for t in sorted(nodig):
        c = yf.download(t, start=begin, auto_adjust=True, progress=False)["Close"]
        h = (c.iloc[:, 0] if hasattr(c, "columns") else c).dropna()   # nooit squeeze: 1 rij wordt een getal
        h.index = h.index.strftime("%Y-%m-%d")
        ruw[t] = h[~h.index.duplicated()]
    df = pd.DataFrame(ruw).sort_index().ffill(limit=MAX_DOORTREKKEN)
    uit = pd.DataFrame(index=df.index)
    for t, v in tickers_valuta.items():
        uit[t] = df[t] / df[FX[v]] if v in FX else df[t]
    return uit


def bijwerken(d, koersen):
    """Alle potjes bijwerken tot en met de laatste dag in `koersen`. Geeft meldingen terug."""
    from datetime import date
    meldingen = []
    for naam, pot in d["potjes"].items():
        if pot.get("status") == "gestopt":
            continue
        namen = list(pot["instrumenten"])
        dagen = [x for x in koersen.index if x >= pot["start"]]
        if pot.get("gestart_op") is None:
            for dag in dagen:
                rij = koersen.loc[dag]
                if all(_geldig(rij.get(n)) for n in namen + [KERN, pot["thema_fonds"]]):
                    start(pot, {n: float(rij[n]) for n in namen}, dag, float(rij[KERN]))
                    pot["maatstaf_start"]["thema"] = float(rij[pot["thema_fonds"]])
                    meldingen.append("%s: gestart op %s" % (naam, dag))
                    break
            else:
                meldingen.append("%s: nog niet gestart (niet alle koersen op of na %s)" % (naam, pot["start"]))
                continue
        for dag in [x for x in dagen if x > pot["laatste_dag"]]:
            rij = koersen.loc[dag]
            open_namen = [n for n, p in pot["posities"].items() if p["open"]]
            if not all(_geldig(rij.get(n)) for n in open_namen + [KERN, pot["thema_fonds"]]):
                meldingen.append("%s: ONMEETBAAR op %s (koers ontbreekt >%d dagen) - stil gezet"
                                 % (naam, dag, MAX_DOORTREKKEN))
                break
            prijzen = {n: float(rij[n]) for n in open_namen}
            verschil = (date.fromisoformat(dag) - date.fromisoformat(pot["laatste_dag"])).days
            verwerk_dag(pot, prijzen, dag, float(rij[KERN]), verschil)
            w = waarde(pot, {**prijzen}, float(rij[KERN]))
            pot.setdefault("reeks", []).append({
                "dag": dag, "waarde_eur": round(w, 4),
                "kern_eur": round(float(pot["inleg_eur"]) * float(rij[KERN]) / pot["maatstaf_start"]["kern"], 4),
                "thema_eur": round(float(pot["inleg_eur"]) * float(rij[pot["thema_fonds"]]) / pot["maatstaf_start"]["thema"], 4),
            })
    return meldingen


def _geldig(x):
    try:
        return x is not None and math.isfinite(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def stand_tekst(d):
    regels = []
    for naam, pot in d["potjes"].items():
        if not pot.get("reeks"):
            regels.append("%-26s nog niet gestart" % naam)
            continue
        z = pot["reeks"][-1]
        inleg = float(pot["inleg_eur"])
        regels.append("%-26s %s  potje %+6.1f%% | kern %+6.1f%% | thema %+6.1f%% | open %d/%d"
                      % (naam, z["dag"], (z["waarde_eur"] / inleg - 1) * 100, (z["kern_eur"] / inleg - 1) * 100,
                         (z["thema_eur"] / inleg - 1) * 100,
                         sum(p["open"] for p in pot["posities"].values()), len(pot["posities"])))
    return "\n".join(regels)


def main(argv):
    opdracht = argv[1] if len(argv) > 1 else "stand"
    d = _laad()
    if opdracht == "bijwerken":
        tickers = {KERN: "EUR"}
        for pot in d["potjes"].values():
            tickers.update(pot["instrumenten"])
            tickers[pot["thema_fonds"]] = "EUR"
        vanaf = min(p["start"] for p in d["potjes"].values())
        # Alleen AFGESLOTEN dagen: de rij van vandaag is tijdens de handel een live koers, en het
        # doortrekken zou ontbrekende VS-koersen van gisteren invullen.
        from datetime import date, timedelta
        tot = (date.today() - timedelta(days=1)).isoformat()
        koersen = _koersen_eur(tickers, vanaf)
        for m in bijwerken(d, koersen[koersen.index <= tot]):
            print(m)
        _schrijf(d)
    print(stand_tekst(d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
