"""Gemeten rendement per rendementsprotocol — de meter achter de M3-poort.

    python -m utils.rendement

Waarom dit bestaat: de poortcriteria stonden in `config/experimenten.json` (min_apr_pct,
min_dagen, max_afwijking_defillama_pp) maar geen regel code las ze. Een poort die niet
gemeten kan worden, kan ook niet gehaald worden — en de regel is "geen experimentgeld vóór
de meter er staat" (A2-audit 2026-09-19, bevinding 1).

Hoe: Check 24 leest elke 5 minuten de share price van elke ERC-4626-vault en Aave's
liquidityIndex. Beide lopen **alleen** op met rendement; storten en opnemen veranderen ze
niet. Twee metingen met een tijdsverschil geven dus een flow-gecorrigeerde APR, zonder dat
we stromen hoeven te boeken:

    APR = (koers_laatst / koers_eerst) ** (365 / dagen) - 1

Onmeetbaar is geen nul: te weinig tijd tussen de metingen, of een ontbrekende reeks, geeft
None — geen 0%.
"""

import json
import os
import sys
import time

STATE_FILE = os.path.join("data", "verliesbewaking_state.json")
REGISTER_FILE = os.path.join("config", "experimenten.json")
BENCHMARK_ID = "aave-v3-arbitrum-usdc"
MIN_DAGEN_ZINVOL = 0.5      # korter dan een halve dag is ruis, geen rendement


def apr_uit_reeks(reeks: dict, nu: float | None = None) -> dict | None:
    """{'apr_pct', 'dagen', 'van', 'tot'} of None als er niet genoeg te meten valt."""
    if not isinstance(reeks, dict):
        return None
    eerste, laatste = reeks.get("eerste") or {}, reeks.get("laatste") or {}
    k0, k1 = eerste.get("koers"), laatste.get("koers")
    t0, t1 = eerste.get("ts"), laatste.get("ts")
    if not (k0 and k1 and t0 and t1) or k0 <= 0:
        return None
    dagen = (float(t1) - float(t0)) / 86400.0
    if dagen < MIN_DAGEN_ZINVOL:
        return None
    groei = float(k1) / float(k0)
    if groei <= 0:
        return None
    apr = (groei ** (365.0 / dagen) - 1.0) * 100.0
    return {"apr_pct": round(apr, 3), "dagen": round(dagen, 2),
            "van": float(t0), "tot": float(t1)}


def poort(pid: str, state: dict, register: dict, defillama_apr_pct: float | None = None,
          nu: float | None = None) -> dict:
    """Toetst één protocol aan zijn poortcriteria uit het register.

    `gehaald` is True, False of **None** (onmeetbaar) — nooit stil False.
    """
    exp = next((e for e in (register.get("experimenten") or {}).values()
                if isinstance(e, dict) and e.get("protocol_id") == pid), {})
    eisen = exp.get("poort") or {}
    gemeten = apr_uit_reeks(((state.get("rendement_reeks") or {}).get(pid) or {}), nu)
    bench = apr_uit_reeks(((state.get("rendement_reeks") or {}).get(BENCHMARK_ID) or {}), nu)
    uit = {"protocol": pid, "gemeten": gemeten, "benchmark": bench, "eisen": eisen,
           "redenen": [], "gehaald": None}
    if gemeten is None:
        uit["redenen"].append("nog geen bruikbare meetreeks")
        return uit

    min_dagen = float(eisen.get("min_dagen", 0) or 0)
    if gemeten["dagen"] < min_dagen:
        uit["redenen"].append("pas %.1f van de %.0f dagen gemeten" % (gemeten["dagen"], min_dagen))
        return uit                       # onmeetbaar, niet gezakt

    gehaald = True
    min_apr = eisen.get("min_apr_pct")
    if min_apr is not None:
        if gemeten["apr_pct"] < float(min_apr):
            gehaald = False
            uit["redenen"].append("APR %.2f%% onder de eis van %.2f%%"
                                  % (gemeten["apr_pct"], float(min_apr)))
        else:
            uit["redenen"].append("APR %.2f%% ≥ %.2f%%" % (gemeten["apr_pct"], float(min_apr)))

    afwijking = eisen.get("max_afwijking_defillama_pp")
    if afwijking is not None:
        if defillama_apr_pct is None:
            uit["gehaald"] = None
            uit["redenen"].append("DeFiLlama-vergelijking ontbreekt — onmeetbaar")
            return uit
        verschil = abs(gemeten["apr_pct"] - float(defillama_apr_pct))
        if verschil > float(afwijking):
            gehaald = False
            uit["redenen"].append("wijkt %.2fpp af van DeFiLlama (max %.2fpp)"
                                  % (verschil, float(afwijking)))
        else:
            uit["redenen"].append("binnen %.2fpp van DeFiLlama" % verschil)

    if bench:
        uit["spread_pp"] = round(gemeten["apr_pct"] - bench["apr_pct"], 3)
        uit["redenen"].append("%.2fpp boven de benchmark (Aave, zelfde venster)"
                              % uit["spread_pp"])
    else:
        uit["redenen"].append("benchmark onmeetbaar — spread onbekend")

    kill = exp.get("kill") or {}
    grens = kill.get("dagen_onder_benchmark")
    if grens is not None:
        onder = dagen_onder_benchmark(state, pid)
        uit["dagen_onder_benchmark"] = onder
        if onder is None:
            uit["redenen"].append("dagen onder de benchmark: onmeetbaar")
        elif onder >= int(grens):
            gehaald = False
            uit["redenen"].append("KILL-regel: %d dagen onder de benchmark (grens %s)"
                                  % (onder, grens))
        else:
            uit["redenen"].append("%d dagen onder de benchmark (grens %s)" % (onder, grens))

    uit["gehaald"] = gehaald
    return uit


def dagen_onder_benchmark(state: dict, pid: str, benchmark_id: str = BENCHMARK_ID) -> int | None:
    """Aantal dagen in de reeks waarin dit protocol minder verdiende dan de benchmark.

    Voor de kill-regel uit het register (`dagen_onder_benchmark`). None als een van beide
    reeksen te kort is: onmeetbaar is geen nul.
    """
    reeksen = state.get("rendement_reeks") or {}
    eigen = (reeksen.get(pid) or {}).get("dagelijks") or []
    bench = (reeksen.get(benchmark_id) or {}).get("dagelijks") or []
    if len(eigen) < 2 or len(bench) < 2:
        return None
    onder = 0
    for i in range(1, min(len(eigen), len(bench))):
        try:
            groei_eigen = eigen[i]["koers"] / eigen[i - 1]["koers"]
            groei_bench = bench[i]["koers"] / bench[i - 1]["koers"]
        except (KeyError, TypeError, ZeroDivisionError):
            return None
        if groei_eigen < groei_bench:
            onder += 1
    return onder


def _lees(pad, standaard):
    try:
        with open(pad, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return standaard


def rapport(state: dict | None = None, register: dict | None = None,
            nu: float | None = None) -> int:
    state = state if state is not None else _lees(STATE_FILE, {})
    register = register if register is not None else _lees(REGISTER_FILE, {})
    reeksen = state.get("rendement_reeks") or {}
    if not reeksen:
        print("Nog geen meetreeks — Check 24 vult hem elke ronde (data/verliesbewaking_state.json).")
        return 1
    nu = nu if nu is not None else time.time()
    print("%-32s %8s %7s %9s" % ("protocol", "APR", "dagen", "t.o.v. Aave"))
    bench = apr_uit_reeks(reeksen.get(BENCHMARK_ID) or {}, nu)
    for pid in sorted(reeksen):
        meting = apr_uit_reeks(reeksen[pid], nu)
        if meting is None:
            print("%-32s %8s %7s %9s" % (pid, "onmeetbaar", "-", "-"))
            continue
        spread = ("%+.2fpp" % (meting["apr_pct"] - bench["apr_pct"])) if bench and pid != BENCHMARK_ID else "-"
        print("%-32s %7.2f%% %7.2f %9s" % (pid, meting["apr_pct"], meting["dagen"], spread))
    for pid in sorted(reeksen):
        if pid == BENCHMARK_ID:
            continue
        p = poort(pid, state, register, nu=nu)
        if p["eisen"]:
            stand = {True: "GEHAALD", False: "NIET GEHAALD", None: "ONMEETBAAR"}[p["gehaald"]]
            print("\npoort %s: %s" % (pid, stand))
            for r in p["redenen"]:
                print("  - %s" % r)
    return 0


if __name__ == "__main__":
    sys.exit(rapport())
