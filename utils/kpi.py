"""KPI's H1–H5 van het plan (2026-09-15, K3) -> data/kpi.json, één regel per dag.

| KPI | Vraag | Bron |
|---|---|---|
| H1 | Is het project netto winstgevend? | potjesreeks + flows + cost_log |
| H2 | Verslaan de beheerde potjes de Aave-rente? | tijdgewogen rendement vs Aave-APY |
| H3 | Blijft experimentverlies onder het budget? | cumulatief resultaat per experiment-potje |
| H4 | Wordt verlies snel gezien? | laatste brandoefening (verliesbewaking) |
| H5 | Is de meting betrouwbaar? | gaten in de reeks, onmeetbare onderdelen |

Definities (vastgelegd, zodat ze niet stil kunnen verschuiven):
- **Opbrengst** = flow-gecorrigeerde winst van `yield_core`, `house` en `basis`, plus de
  toename van het GEREALISEERDE resultaat van de dip-koper. Koersbeweging van de kern,
  de dip-koper-posities en crypto-vasthouden telt niet: dat is markt, geen opbrengst.
- **Kosten** = `total_cost_usd` uit cost_log.json (VM + LLM + fees) per dag.
- **Rendement per dag** = Modified Dietz: (V1 - V0 - F) / (V0 + F/2).
- Het venster telt alleen dagen waarvoor snapshot én kosten bekend zijn; minder dan 90
  dagen heet `voorlopig`.

Weigert NaN of inf: dan wordt er niets geschreven en staat het in de log. Een KPI die
er stil als getal staat terwijl hij onmeetbaar is, is precies de scorekaart-fout.
"""

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone

from utils import flows

logger = logging.getLogger("KPI")

KPI_FILE = "data/kpi.json"
SLEEVE_NAV_FILE = "data/sleeve_nav.json"
COST_LOG_FILE = "cost_log.json"
REGISTER_FILE = "config/experimenten.json"
TREASURY_STATE_FILE = "treasury_state.json"
THEMATIC_FILE = "thematic_exposure_positions.json"
VERLIES_STATE_FILE = "data/verliesbewaking_state.json"

BEHEERD = ("yield_core", "house", "basis")
VENSTER_DAGEN = 90
GATEN_VENSTER = 30
MAX_HISTORIE = 400


def niet_eindig(obj, pad=""):
    """Paden naar NaN/inf in een geneste structuur. Leeg = schoon."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return [pad or "<wortel>"]
    if isinstance(obj, dict):
        return [p for k, v in obj.items()
                for p in niet_eindig(v, "%s.%s" % (pad, k) if pad else str(k))]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in niet_eindig(v, "%s[%d]" % (pad, i))]
    return []


def _dietz(v0, v1, f):
    winst = v1 - v0 - f
    noemer = v0 + 0.5 * f
    return winst, (winst / noemer if noemer > 0 else None)


def bereken(hist, stromen, register, kosten_per_dag, aave_apy_per_dag,
            dip_per_dag, verlies_state, vandaag, venster=VENSTER_DAGEN):
    """Puur. `hist` = sleeve_nav-historie; de rest zijn dicts {datum: waarde}."""
    hist = sorted((h for h in hist if h.get("date") and h.get("sleeves") is not None),
                  key=lambda h: h["date"])
    # Eerst de hele reeks op NaN/inf, los van kosten en venster. Anders glipt een NaN
    # stil door op elke dag waarvoor (nog) geen kosten bekend zijn — de lus slaat die
    # dag dan over en leest de waarde nooit (gevonden door de pre-deploy-poort).
    vuil_invoer = niet_eindig([h.get("sleeves") for h in hist])
    if vuil_invoer:
        raise ValueError("Potjesreeks bevat NaN/inf op %s — geen KPI berekend"
                         % ", ".join(vuil_invoer[:5]))
    onmeetbaar = []

    # ── H1 + H2 over het venster ─────────────────────────────────────────
    stukken = hist[-(venster + 1):]
    opbrengst_potjes = {s: 0.0 for s in BEHEERD}
    kosten = 0.0
    groei = 1.0
    dagen = 0
    datums = []
    for vorige, huidige in zip(stukken, stukken[1:]):
        d = huidige["date"]
        # Snapshots vallen rond 00:05 UTC: het interval (gisteren, vandaag] is vrijwel
        # helemaal GISTEREN. De kosten van die dag horen erbij, niet die van vandaag.
        kosten_dag = vorige["date"]
        if kosten_dag not in kosten_per_dag:
            continue    # zonder kosten geen eerlijke netto-dag
        t0, t1 = flows._epoch(vorige.get("ts")), flows._epoch(huidige.get("ts"))
        if t0 is None or t1 is None:
            onmeetbaar.append("ts:%s" % d)
            continue
        v0c = v1c = fc = 0.0
        for s in BEHEERD:
            v0 = float(vorige["sleeves"].get(s, 0.0) or 0.0)
            v1 = float(huidige["sleeves"].get(s, 0.0) or 0.0)
            f = flows.netto_flow(stromen, s, t0, t1)
            winst, _ = _dietz(v0, v1, f)
            opbrengst_potjes[s] += winst
            v0c, v1c, fc = v0c + v0, v1c + v1, fc + f
        _, r = _dietz(v0c, v1c, fc)
        if r is not None:
            groei *= (1.0 + r)
        kosten += float(kosten_per_dag[kosten_dag])
        dagen += 1
        datums.append(d)

    dip = [dip_per_dag[d] for d in sorted(dip_per_dag) if datums and datums[0] <= d <= datums[-1]]
    dip_delta = (dip[-1] - dip[0]) if len(dip) >= 2 else 0.0
    opbrengst = sum(opbrengst_potjes.values()) + dip_delta

    rendement_jaar_pct = ((groei ** (365.0 / dagen) - 1.0) * 100.0) if dagen else None
    aave = [aave_apy_per_dag[d] for d in datums if d in aave_apy_per_dag]
    aave_gem = sum(aave) / len(aave) if aave else None
    if rendement_jaar_pct is not None and aave_gem is None:
        onmeetbaar.append("aave_apy")

    h1 = {"opbrengst_usd": round(opbrengst, 2), "kosten_usd": round(kosten, 2),
          "netto_usd": round(opbrengst - kosten, 2), "dagen": dagen,
          "voorlopig": dagen < venster,
          "per_potje_usd": {k: round(v, 2) for k, v in opbrengst_potjes.items()},
          "dip_koper_gerealiseerd_usd": round(dip_delta, 2),
          "doel_gehaald": (opbrengst - kosten) > 0}
    h2 = {"rendement_jaar_pct": None if rendement_jaar_pct is None else round(rendement_jaar_pct, 2),
          "aave_apy_pct": None if aave_gem is None else round(aave_gem, 3),
          "verschil_pp": (None if rendement_jaar_pct is None or aave_gem is None
                          else round(rendement_jaar_pct - aave_gem, 2)),
          "doel_pp": 2.0}
    h2["doel_gehaald"] = h2["verschil_pp"] is not None and h2["verschil_pp"] >= h2["doel_pp"]

    # ── H3: experimentverlies sinds de start van elk experiment-potje ─────
    globaal = register.get("globaal") or {}
    verlies_per = {}
    for naam, exp in (register.get("experimenten") or {}).items():
        potje = exp.get("sleeve")
        if not potje or not exp.get("verliesbudget_telt_mee"):
            continue
        cumulatief, gestart = 0.0, False
        for vorige, huidige in zip(hist, hist[1:]):
            v0 = float(vorige["sleeves"].get(potje, 0.0) or 0.0)
            v1 = float(huidige["sleeves"].get(potje, 0.0) or 0.0)
            t0, t1 = flows._epoch(vorige.get("ts")), flows._epoch(huidige.get("ts"))
            if t0 is None or t1 is None:
                continue
            f = flows.netto_flow(stromen, potje, t0, t1)
            if not gestart and v1 <= 0 and f <= 0:
                continue
            gestart = True
            cumulatief += _dietz(v0, v1, f)[0]
        verlies_per[naam] = round(max(0.0, -cumulatief), 2)
    verlies = sum(verlies_per.values())
    budget = float(globaal.get("verliesbudget_usd", 250))
    h3 = {"verlies_usd": round(verlies, 2), "per_experiment_usd": verlies_per,
          "budget_usd": budget, "alarm_usd": float(globaal.get("verliesbudget_alarm_usd", budget / 2)),
          "doel_gehaald": verlies < budget}

    # ── H4: laatste brandoefening ────────────────────────────────────────
    oef = (verlies_state or {}).get("laatste_oefening") or {}
    doel_min = float(globaal.get("detectie_doel_minuten", 10))
    h4 = {"detectie_min": oef.get("detectie_min"), "alles_gevonden": oef.get("alles_gevonden"),
          "doel_min": doel_min,
          "doel_gehaald": bool(oef.get("alles_gevonden")) and oef.get("detectie_min") is not None
          and float(oef["detectie_min"]) <= doel_min}

    # ── H5: betrouwbaarheid van de meting ────────────────────────────────
    aanwezig = {h["date"] for h in hist}
    dag = datetime.strptime(vandaag, "%Y-%m-%d").date()
    eerste = min(aanwezig) if aanwezig else vandaag
    verwacht = [(dag - timedelta(days=i)).isoformat() for i in range(GATEN_VENSTER)]
    gaten = sorted(d for d in verwacht if d >= eerste and d not in aanwezig)
    h5 = {"gaten_30d": len(gaten), "gaten": gaten, "onmeetbaar": onmeetbaar,
          "doel_gehaald": not gaten and not onmeetbaar}

    uit = {"h1": h1, "h2": h2, "h3": h3, "h4": h4, "h5": h5}
    vuil = niet_eindig(uit)
    if vuil:
        raise ValueError("KPI bevat NaN/inf op %s — niet weggeschreven" % ", ".join(vuil[:5]))
    return uit


def _lees(pad, standaard):
    try:
        with open(pad, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return standaard


def _aave_apy_vandaag(treasury_state):
    for o in treasury_state.get("opportunities") or []:
        cfg = o.get("protocol_config") or {}
        if cfg.get("id") == "aave-v3-arbitrum-usdc":
            try:
                v = float(o.get("apy"))
                return v if math.isfinite(v) else None
            except (TypeError, ValueError):
                return None
    return None


def update_kpi(nu=None, kpi_pad=KPI_FILE):
    """Rekent de KPI's van vandaag uit en schrijft ze weg. None als de basis ontbreekt."""
    nu = nu or datetime.now(timezone.utc)
    vandaag = nu.strftime("%Y-%m-%d")
    hist = (_lees(SLEEVE_NAV_FILE, {}) or {}).get("history") or []
    if not hist:
        logger.warning("KPI: geen potjesreeks in %s — niets berekend", SLEEVE_NAV_FILE)
        return None

    register = _lees(REGISTER_FILE, {}) or {}
    bestand = _lees(kpi_pad, {"history": []}) or {"history": []}
    oud = [e for e in bestand.get("history") or [] if e.get("date") != vandaag]

    onmeetbaar_extra = []
    try:
        stromen = flows.laad_flows()
    except flows.FlowsOnleesbaar as e:
        logger.error("KPI: %s", e)
        stromen, onmeetbaar_extra = [], ["flows"]

    # Kosten per dag blijven in kpi.json bewaard: cost_log houdt maar 30 dagen bij.
    # Waarden uit cost_log overschrijven eerdere (een dag is pas af als hij voorbij is).
    kosten = dict(bestand.get("kosten_per_dag") or {})
    for d, regel in ((_lees(COST_LOG_FILE, {}) or {}).get("history") or {}).items():
        try:
            v = float(regel.get("total_cost_usd"))
            if math.isfinite(v):
                kosten[d] = v
        except (TypeError, ValueError, AttributeError):
            pass

    ts = _lees(TREASURY_STATE_FILE, {}) or {}
    aave_vandaag = _aave_apy_vandaag(ts)
    aave = {e["date"]: e["aave_apy_pct"] for e in oud if e.get("aave_apy_pct") is not None}
    if aave_vandaag is not None:
        aave[vandaag] = aave_vandaag

    them = _lees(THEMATIC_FILE, {}) or {}
    dip_vandaag = them.get("realized_pnl_usd")
    dip = {e["date"]: e["dip_gerealiseerd_usd"] for e in oud
           if e.get("dip_gerealiseerd_usd") is not None}
    try:
        if dip_vandaag is not None and math.isfinite(float(dip_vandaag)):
            dip[vandaag] = float(dip_vandaag)
    except (TypeError, ValueError):
        pass

    uitkomst = bereken(hist, stromen, register, kosten, aave, dip,
                       _lees(VERLIES_STATE_FILE, {}) or {}, vandaag)
    uitkomst["h5"]["onmeetbaar"] += onmeetbaar_extra
    if onmeetbaar_extra:
        uitkomst["h5"]["doel_gehaald"] = False
        uitkomst["h1"]["netto_usd"] = None
        uitkomst["h2"]["verschil_pp"] = None

    regel = {"date": vandaag, "ts": nu.isoformat(), "kosten_usd": kosten.get(vandaag),
             "aave_apy_pct": aave_vandaag, "dip_gerealiseerd_usd": dip.get(vandaag)}
    regel.update(uitkomst)
    vuil = niet_eindig(regel)
    if vuil:
        raise ValueError("KPI-regel bevat NaN/inf op %s — niet weggeschreven" % ", ".join(vuil[:5]))

    historie = (oud + [regel])[-MAX_HISTORIE:]
    map_ = os.path.dirname(kpi_pad)
    if map_:
        os.makedirs(map_, exist_ok=True)
    with open(kpi_pad, "w", encoding="utf-8") as fh:   # in-place: data/ is een bind mount
        json.dump({"history": historie, "laatste": regel,
                   "kosten_per_dag": dict(sorted(kosten.items())[-MAX_HISTORIE:])},
                  fh, indent=2, ensure_ascii=False)
    logger.info("[KPI] %s: netto $%s over %d dagen, verschil vs Aave %s pp",
                vandaag, uitkomst["h1"]["netto_usd"], uitkomst["h1"]["dagen"],
                uitkomst["h2"]["verschil_pp"])
    return regel


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = update_kpi()
    print(json.dumps(r, indent=2, ensure_ascii=False) if r else "Geen KPI berekend.")
