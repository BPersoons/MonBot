"""Overzichtspagina "Waar we staan" — vermogen over tijd, de motor, schaduwpotjes, signalen.

    python scripts/overzicht.py --vm   # eerst de stand van de VM ophalen (gcloud), dan bouwen
    python scripts/overzicht.py        # bouwen met de laatste vm_snapshot.json

Bouwt docs/overzicht_artifact.html. Publiceer die met de `url` uit memory
`reference_overzichtspagina` (favicon 📊 blijft staan) — nooit zonder url, anders ontstaat
er een tweede pagina.

Opzet (22-09, op verzoek van Bart: "ik wil af en toe inloggen en zien hoe het ervoor staat"):
de DATA wordt hier verzameld en als JSON in de pagina gezet; het TEKENEN gebeurt in
scripts/overzicht_sjabloon.html. Zo kan de vormgeving veranderen zonder de meting aan te
raken, en andersom.

Bronnen: de VM (NAV per potje, vermogen per dag, KPI's), het register
(config/experimenten.json), research/ (schaduwpotjes, uitstapsignaal, scorekaart, thema's).
Onmeetbaar is geen nul: ontbreekt een bron, dan staat dat op de pagina.
"""

import argparse
import base64
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

WORTEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WORTEL, "research"))
import track  # noqa: E402

UIT = os.path.join(WORTEL, "docs", "overzicht_artifact.html")
SJABLOON = os.path.join(WORTEL, "scripts", "overzicht_sjabloon.html")
VM_SNAPSHOT = os.path.join(WORTEL, "vm_snapshot.json")      # gitignored: bevat saldi

# ── potjes in de grafiek: vaste kleur per potje (dataviz: kleur volgt het potje) ─────
# Volgorde = stapelvolgorde van onder naar boven = palet-slotvolgorde (gevalideerd 22-09,
# licht en donker, aangrenzende paren).
GROEPEN = [
    ("degiro", "DeGiro — wereldindex + GRID", ("tradfi",)),
    ("dip", "Dip-koper (Hyperliquid)", ("thematic_exposure", "thematic_dip", "lab")),
    ("rente", "Rente (kasbeheer)", ("yield_core", "house")),
    ("crypto", "Crypto vasthouden", ("conviction_core",)),
    ("hlkas", "Kas op Hyperliquid", ("swarm", "basis")),
]

# Gewone namen voor het register (docs/NAMEN.md: gebruik in gesprek de gewone naam).
NAMEN = {
    "dip_koper": "Dip-koper", "fluid_rente": "Fluid-rente", "hlp_vault": "HLP-vault",
    "basis_traag": "Trage basis-trade", "dip_koper_beursstops": "Stops op de beurs",
    "pendle_vaste_rente": "Pendle vaste rente", "gains_gusdc_house": "Gains-vault",
    "morpho_tweede_bestemming": "Morpho als tweede bestemming",
    "dip_koper_marktfilter": "Marktfilter dip-koper", "e2_micro_poging_2": "Goedkopere VM (2e poging)",
    "sector_momentum": "Sectormomentum", "industrie_momentum": "Industriemomentum",
    "thema_radar_keten": "Thema-radar per keten", "uitstapregel_crash": "Uitstapsignaal WEBN",
    "uitstapregel_crypto": "Uitstapregel crypto", "uitstapregel_thema": "Uitstapregel thema's",
    "risicopotjes_etf": "Risicopotjes (ETF's)", "crypto_vol_target": "Crypto vol-targeting",
    "uitschieterpotje": "Uitschieterpotje", "schaduw_ai_tolhuisje": "AI-tolhuisje (schaduw)",
    "schaduw_splijtstof": "Splijtstof-knelpunten (schaduw)", "schaduw_net_tolhuisje": "Net-tolhuisje (schaduw)",
}

# Wat alleen Bart kan beslissen. Met de hand bijgehouden: een beslissing is geen meting.
BESLISSINGEN = [
    ("2026-09-25", "Dip-koper: doorgaan, stoppen of vervangen door een Nasdaq-ETF?",
     "60 dagen: +$27,72 netto gerealiseerd op $255, maar op 16 jaar data gedraagt hij zich als de "
     "Nasdaq-100. Een ETF doet hetzelfde zonder code en VM. Advies volgt op 25-09."),
    ("2026-11-03", "Uitstapsignaal WEBN: de regel, of een vaste mix?",
     "De regel is een verzekering tegen trage crashes (2008: daling 25% i.p.v. 42%), maar kost in "
     "gewone jaren 1,5-3 procentpunt per jaar tegen een vaste mix van ~75% WEBN / 25% geldmarkt."),
    ("open", "Fluid als tweede rentebestemming?",
     "Fluid geeft 4,2% tegen Aave 2,6% (30 dagen), goed voor +$13-26 per jaar, tegen extra protocolrisico op "
     "tot $1.619. Advies: overslaan tot het verschil groter is."),
]

VM_SCRIPT = r'''
import json, time
uit = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
try:
    from utils.nav import compute_nav
    uit["nav"] = compute_nav()
except Exception as e:
    uit["nav_fout"] = str(e)[:200]
try:
    cc = json.load(open("conviction_core_state.json"))
    kost, eerste = 0.0, None
    for r in cc.get("history", []):
        for t in r.get("trades", []):
            kost += float(t.get("usd") or 0) * (1 if t.get("side") == "buy" else -1)
            eerste = eerste or r.get("ts")
    uit["crypto_kost"] = {"usd": round(kost, 2), "sinds": eerste}
except Exception as e:
    uit["crypto_kost_fout"] = str(e)[:200]
for k, p in (("sleeve_nav", "data/sleeve_nav.json"), ("kpi", "data/kpi.json")):
    try:
        uit[k] = json.load(open(p))
    except Exception as e:
        uit[k + "_fout"] = str(e)[:200]
print("<<<JSON"); print(json.dumps(uit, default=str)); print("JSON>>>")
'''


def haal_vm():
    b64 = base64.b64encode(VM_SCRIPT.encode()).decode()
    cmd = ('gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command="echo %s | '
           'base64 -d | sudo docker exec -i -w /app agent_trader_swarm python3 -"' % b64)
    uit = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=240).stdout
    if "<<<JSON" not in uit:
        raise RuntimeError("geen JSON van de VM")
    data = json.loads(uit.split("<<<JSON", 1)[1].split("JSON>>>", 1)[0])
    with io.open(VM_SNAPSHOT, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def _laad(pad, standaard=None):
    try:
        with io.open(os.path.join(WORTEL, pad), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return standaard


def _koersen(tickers):
    """Live koersen; ontbrekende blijven None — nooit als 0 tellen."""
    try:
        import yfinance as yf
        data = yf.download(list(tickers), period="5d", progress=False, auto_adjust=True)["Close"]
        uit = {}
        for t in tickers:
            try:
                s = data[t].dropna() if t in data.columns else None
                uit[t] = float(s.iloc[-1]) if s is not None and len(s) else None
            except Exception:
                uit[t] = None
        return uit
    except Exception:
        return {t: None for t in tickers}


# ── onderdelen ──────────────────────────────────────────────────────────────────────

def vermogen(vm):
    """Huidige potjes + de reeks per dag, gegroepeerd; plus wanneer een potje voor het eerst meetelde."""
    nav = vm.get("nav") or {}
    potjes = [{"label": p.get("label"), "waarde_usd": p.get("waarde_usd"), "status": p.get("status"),
               "detail": p.get("detail", "")} for p in nav.get("potjes", [])]
    reeks, eerste = [], {}
    for r in (vm.get("sleeve_nav") or {}).get("history", []):
        s = r.get("sleeves") or {}
        groepen = {}
        for sleutel, _label, bronnen in GROEPEN:
            w = sum(float(s.get(b) or 0.0) for b in bronnen)
            groepen[sleutel] = round(w, 2)
            if w > 0 and sleutel not in eerste:
                eerste[sleutel] = r.get("date")
        reeks.append({"d": r.get("date"), "g": groepen, "t": round(float(r.get("total_usd") or 0.0), 2),
                      "eurusd": r.get("eurusd")})
    start = reeks[0]["d"] if reeks else None
    markeringen = [{"d": d, "groep": g} for g, d in eerste.items() if d and d != start]
    return {"totaal_usd": nav.get("totaal_usd"), "compleet": nav.get("compleet"), "potjes": potjes,
            "reeks": reeks, "markeringen": markeringen,
            "groepen": [{"sleutel": k, "label": l} for k, l, _b in GROEPEN]}


def motor():
    reg = _laad("config/experimenten.json", {}) or {}
    treden = {str(t): [] for t in range(5)}
    gestopt = []
    for sleutel, e in (reg.get("experimenten") or {}).items():
        if not isinstance(e, dict):
            continue
        item = {"sleutel": sleutel, "naam": NAMEN.get(sleutel, sleutel.replace("_", " ").capitalize()),
                "status": e.get("status"), "trede": e.get("trede"), "sinds": e.get("sinds"),
                "herzien": e.get("herzien"), "budget": e.get("budget_usd"),
                "volgende": e.get("volgende_stap") or "", "hypothese": e.get("hypothese") or "",
                "kaart": e.get("kaart") or {}}
        if e.get("status") == "gestopt":
            gestopt.append(item)
        elif str(e.get("trede")) in treden:
            treden[str(e.get("trede"))].append(item)
    g = reg.get("globaal") or {}
    return {"treden": treden, "gestopt": gestopt,
            "proeftuin_kapitaal": g.get("proeftuin_kapitaal_usd"), "verliesbudget": g.get("verliesbudget_usd")}


def schaduw():
    d = _laad("research/schaduwpotjes.json", {}) or {}
    uit = []
    for sleutel, p in (d.get("potjes") or {}).items():
        uit.append({"sleutel": sleutel, "naam": sleutel.replace("_", " "), "these": p.get("these"),
                    "instrumenten": list((p.get("instrumenten") or {}).keys()), "thema_fonds": p.get("thema_fonds"),
                    "start": p.get("start"), "gestart_op": p.get("gestart_op"), "inleg": p.get("inleg_eur"),
                    "reeks": p.get("reeks") or [], "gebeurtenissen": (p.get("gebeurtenissen") or [])[-5:],
                    "open": sum(1 for x in (p.get("posities") or {}).values() if x.get("open")),
                    "posities": len(p.get("posities") or {}), "evalueer_op": p.get("evalueer_op"),
                    "uitvoering": p.get("uitvoering")})
    return uit


def signalen(vm, namen_rijen):
    u = _laad("research/uitstap_signaal.json", {}) or {}
    m = (u.get("maanden") or [])[-1:] or [None]
    m = m[0]
    uitstap = None
    if m:
        uitstap = {"maand": m["maand"], "slot": m["slot"], "gem10": m["gem10"], "stand": m["stand"],
                   "pct": round((m["slot"] / m["gem10"] - 1) * 100, 1), "controle": m.get("controle_stand")}
    kpi = ((vm.get("kpi") or {}).get("laatste")) or {}
    gemeten = [r["rel"] for r in namen_rijen if r["rel"] is not None]
    prijs = [r for r in namen_rijen if r["afstand"] is not None and r["verdict"] != "AFVALLER"]
    dichtst = max(prijs, key=lambda r: r["afstand"]) if prijs else None
    return {"uitstap": uitstap, "kpi": kpi,
            "scorekaart": {"n": len(namen_rijen), "gem_rel": round(sum(gemeten) / len(gemeten), 2) if gemeten else None,
                           "dichtst": {"t": dichtst["t"], "afstand": round(dichtst["afstand"], 1), "wp": dichtst["wp"]}
                           if dichtst else None,
                           "geraakt": [r["t"] for r in prijs if r["afstand"] >= 0]}}


def namen():
    ledger = _laad("research/ledger.json", {"entries": []})
    actief = [e for e in ledger.get("entries", []) if not e.get("superseded_by")]
    bench = track.bench_config(ledger)
    nodig = [e["ticker"] for e in actief] + [bench["ticker"]] + ([bench["fx_ticker"]] if bench["fx_ticker"] else [])
    prijzen = _koersen(nodig)
    bench_nu = prijzen.get(bench["ticker"])
    fx_nu = prijzen.get(bench["fx_ticker"]) if bench["fx_ticker"] else None
    rijen = []
    for e in actief:
        nu = prijzen.get(e["ticker"])
        rend, bench_rend = track.returns_pct(e, nu, bench_nu, fx_nu, bench)
        wp = e.get("wait_price_below")
        rijen.append({"t": e["ticker"], "naam": e.get("name", ""), "verdict": e["verdict"],
                      "gescoord": e.get("scored_at"), "nu": nu,
                      "rel": round(rend - bench_rend, 2) if rend is not None and bench_rend is not None else None,
                      "wp": wp, "afstand": ((wp / nu - 1) * 100) if (wp and nu) else None,
                      "wacht": (e.get("wait_conditions") or ["—"])[0][:120]})
    rijen.sort(key=lambda r: ({"KOOPBAAR": 0, "VOLGEN": 1, "AFVALLER": 2}.get(r["verdict"], 3),
                              -(r["afstand"] if r["afstand"] is not None else -999)))
    return rijen


def themas():
    uit = []
    for k in (_laad("research/themes.json", {}) or {}).get("kaarten", []):
        uit.append({"naam": k.get("naam"), "verdict": k.get("verdict"), "tolhuisje": k.get("tolhuisje_schakel"),
                    "herzien": "herziening_2026_09_21" in k})
    return uit


# ── live meters: "hoe dicht zitten we erbij" (Bart 22-09) ─────────────────────────────

HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"


def _hl(body):
    import urllib.request
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _llama_pools():
    import urllib.request
    with urllib.request.urlopen("https://yields.llama.fi/pools", timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))["data"]


def _llama(pools, project):
    kand = [p for p in pools if p.get("project") == project and p.get("chain") == "Arbitrum"
            and (p.get("symbol") or "").upper() in ("USDC", "USDC.E")]
    return max(kand, key=lambda p: p.get("tvlUsd") or 0) if kand else None


def _funding_apr(coin, dagen=30):
    import time
    start = int((time.time() - dagen * 86400) * 1000)
    rij = []
    while True:
        r = _hl({"type": "fundingHistory", "coin": coin, "startTime": start})
        if not r:
            break
        rij += r
        if len(r) < 500:
            break
        start = r[-1]["time"] + 1
    if not rij:
        return None
    return sum(float(x["fundingRate"]) for x in rij) / len(rij) * 24 * 365 * 100


def meters(vm, schaduw_potjes, uitstap):
    """{bron: {"nu": getal|None, "grens": getal|None, "info": tekst}}. Onmeetbaar = None, nooit 0."""
    uit = {}

    def veilig(naam, fn):
        try:
            uit[naam] = fn()
        except Exception as e:
            uit[naam] = {"nu": None, "grens": None, "info": "niet te meten (%s)" % str(e)[:60]}

    kpi = ((vm.get("kpi") or {}).get("laatste")) or {}
    aave = kpi.get("aave_apy_pct")

    def dip():
        # Alleen vanaf de eigen wallet (23-07): daarvoor was het potje groter en is er geld
        # UITgehaald. Die verplaatsing als 'daling' tellen is de bekende valse drawdown.
        reeks = [float((r.get("sleeves") or {}).get("thematic_exposure") or 0)
                 for r in (vm.get("sleeve_nav") or {}).get("history", []) if (r.get("date") or "") >= "2026-07-23"]
        reeks = [x for x in reeks if x > 0]
        top = max(reeks)
        return {"nu": round((1 - reeks[-1] / top) * 100, 1), "grens": 15.0,
                "info": "top $%.0f, nu $%.0f" % (top, reeks[-1])}
    veilig("dip_daling", dip)
    uit["uitstap_webn"] = {"nu": uitstap["pct"] if uitstap else None, "grens": 0.0,
                           "info": ("slot %s" % uitstap["maand"]) if uitstap else ""}
    pools = None
    try:
        pools = _llama_pools()
    except Exception as e:
        uit["_llama_fout"] = {"nu": None, "grens": None, "info": str(e)[:80]}
    fluid = _llama(pools, "fluid-lending") if pools else None
    aave_p = _llama(pools, "aave-v3") if pools else None
    gains = _llama(pools, "gains-network") if pools else None
    fluid30 = fluid.get("apyMean30d") if fluid else None

    def spread():
        a = aave_p.get("apyMean30d")
        return {"nu": round(fluid30 - a, 2), "grens": None,
                "info": "Fluid %.1f%% · Aave %.1f%% (30 dagen, DeFiLlama)" % (fluid30, a)}
    veilig("fluid_spread", spread)

    def hlp():
        apr = float(_hl({"type": "vaultDetails", "vaultAddress": HLP})["apr"]) * 100
        return {"nu": round(apr, 2), "grens": round(aave + 3, 2) if aave else None,
                "info": ("Aave nu %.1f%%" % aave) if aave else ""}
    veilig("hlp_apr", hlp)

    def basis():
        # Op KAPITAAL, zoals de backtest en de vergelijking met Fluid: bij 2x hefboom is het
        # ingezette kapitaal 1,5x de notional (spot 1 + marge 0,5), dus funding / 1,5.
        waarden = [v for v in (_funding_apr(c) for c in ("BTC", "ETH", "HYPE")) if v is not None]
        ruw = sum(waarden) / len(waarden)
        return {"nu": round(ruw / 1.5, 2), "grens": round(fluid30 + 3, 2) if fluid30 else None,
                "info": ("op kapitaal bij 2x; ruwe funding %.1f%% (gemiddelde BTC, ETH, HYPE); Fluid %.1f%%"
                         % (ruw, fluid30)) if fluid30 else ""}
    veilig("basis_funding", basis)

    def gains_tvl():
        return {"nu": round(gains["tvlUsd"] / 1e6, 2), "grens": 5.0,
                "info": "rente 30 dagen %.1f%%" % (gains.get("apyMean30d") or 0)}
    veilig("gains_tvl", gains_tvl)

    for p in schaduw_potjes:
        r = p["reeks"]
        if r:
            z = r[-1]
            uit["schaduw:" + p["sleutel"]] = {
                "nu": round((z["waarde_eur"] - z["thema_eur"]) / p["inleg"] * 100, 1), "grens": 10.0,
                "info": "potje %+.1f%% · kern %+.1f%% · themafonds %+.1f%%" % (
                    (z["waarde_eur"] / p["inleg"] - 1) * 100, (z["kern_eur"] / p["inleg"] - 1) * 100,
                    (z["thema_eur"] / p["inleg"] - 1) * 100)}
        else:
            uit["schaduw:" + p["sleutel"]] = {"nu": None, "grens": 10.0,
                                              "info": "eerste meting na het volgende slot"}
    return uit


def rendement(vm):
    """Winst of verlies per potje sinds zijn eigen start, met WEBN over dezelfde periode.
    Waar een kostprijs ontbreekt: None (onbekend), nooit 0."""
    import yfinance as yf
    uit = []
    webn = yf.download("WEBN.DE", start="2026-07-01", auto_adjust=True, progress=False)["Close"]
    webn = (webn.iloc[:, 0] if hasattr(webn, "columns") else webn).dropna()
    webn.index = webn.index.strftime("%Y-%m-%d")

    def webn_sinds(dag):
        v = webn[webn.index >= dag]
        return round((float(webn.iloc[-1]) / float(v.iloc[0]) - 1) * 100, 2) if len(v) else None

    potjes = {p["sleutel"]: p for p in ((vm.get("nav") or {}).get("potjes") or [])}
    bh = _laad("config/broker_holdings.json", {}) or {}
    for pos in bh.get("posities", []):
        nu = float(webn.iloc[-1]) if pos["ticker"] == "WEBN" else None
        if pos["ticker"] != "WEBN":
            try:
                g = yf.download(pos["yahoo_ticker"], period="5d", auto_adjust=True, progress=False)["Close"]
                g = (g.iloc[:, 0] if hasattr(g, "columns") else g).dropna()
                nu = float(g.iloc[-1])
            except Exception:
                nu = None
        waarde = pos["aantal"] * nu if nu else None
        kost = pos.get("kostprijs_eur")
        uit.append({"naam": "WEBN — wereldindex" if pos["ticker"] == "WEBN" else "GRID — stroom en net",
                    "groep": "degiro", "valuta": "EUR", "inleg": kost,
                    "waarde": round(waarde, 2) if waarde else None, "sinds": pos.get("gekocht_op"),
                    "pct": round((waarde / kost - 1) * 100, 2) if (waarde and kost) else None,
                    "webn_pct": None if pos["ticker"] == "WEBN" else webn_sinds(pos.get("gekocht_op"))})
    dip = potjes.get("dip_koper", {}).get("waarde_usd")
    uit.append({"naam": "Dip-koper", "groep": "dip", "valuta": "USD", "inleg": 255.0, "waarde": dip,
                "sinds": "2026-07-23", "pct": round((dip / 255.0 - 1) * 100, 2) if dip else None,
                "webn_pct": webn_sinds("2026-07-23")})
    ck = vm.get("crypto_kost") or {}
    cw = potjes.get("crypto_vasthouden", {}).get("waarde_usd")
    ks = ck.get("usd")
    sinds = (ck.get("sinds") or "")[:10] or None
    uit.append({"naam": "Crypto vasthouden", "groep": "crypto", "valuta": "USD", "inleg": ks, "waarde": cw,
                "sinds": sinds, "pct": round((cw / ks - 1) * 100, 2) if (cw and ks) else None,
                "webn_pct": webn_sinds(sinds) if sinds else None})
    kpi = ((vm.get("kpi") or {}).get("laatste")) or {}
    rente = {"jaar_pct": (kpi.get("h2") or {}).get("rendement_jaar_pct"), "aave_pct": kpi.get("aave_apy_pct"),
             "waarde": potjes.get("veilig", {}).get("waarde_usd")}
    return {"potjes": uit, "rente": rente}


def bouw(vm):
    rijen = namen()
    sch = schaduw()
    sig = signalen(vm, rijen)
    data = {
        "gebouwd": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vm_ts": vm.get("ts"),
        "fouten": [v for k, v in vm.items() if k.endswith("_fout")],
        "vermogen": vermogen(vm),
        "motor": motor(),
        "schaduw": sch,
        "signalen": sig,
        "meters": meters(vm, sch, sig["uitstap"]),
        "rendement": rendement(vm),
        "namen": rijen,
        "themas": themas(),
        "beslissingen": [{"wanneer": w, "vraag": v, "uitleg": u} for w, v, u in BESLISSINGEN],
    }
    js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with io.open(SJABLOON, encoding="utf-8") as fh:
        html = fh.read()
    assert "/*DATA*/null" in html, "sjabloon mist de plek voor de data"
    html = html.replace("/*DATA*/null", js)
    with io.open(UIT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vm", action="store_true", help="eerst de stand van de VM ophalen")
    a = ap.parse_args()
    if a.vm:
        vm = haal_vm()
    else:
        with io.open(VM_SNAPSHOT, encoding="utf-8") as fh:
            vm = json.load(fh)
    data = bouw(vm)
    print("gebouwd: %s  (VM-stand %s, %d dagen vermogen, %d namen)"
          % (UIT, data["vm_ts"], len(data["vermogen"]["reeks"]), len(data["namen"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
