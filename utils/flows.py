"""Kapitaalstromen tussen potjes — de noemer onder elk rendement (plan 2026-09-15, K1).

Waarom dit bestaat: een overboeking van Aave naar HLP of een storting bij de broker is
geen winst en geen verlies. Zonder deze boekhouding ziet elke KPI een storting als
rendement en een overboeking als drawdown — de valse-drawdown-valkuil uit CLAUDE.md.

Twee bronnen, bewust:

1. `treasury_proposals.json` — kasbeheer legt elke uitgevoerde beweging al vast, met
   bedrag, status en tijd. Afleiden is beter dan elke executor een tweede keer laten
   boeken: dan staat dezelfde stroom op twee plekken en lopen die uit elkaar.
2. `data/flows.json` — alles wat kasbeheer niet ziet: stortingen bij de broker, HLP in
   en uit, basis-kapitaal, handmatige correcties. Alleen toevoegen, nooit herschrijven.

Potjesnamen zijn die uit `config/sleeves.json` (yield_core, swarm, thematic_exposure,
house, basis, tradfi, conviction_core). Geld van buiten heet `extern`.
"""

import json
import logging
import math
import os
from datetime import datetime, timezone

logger = logging.getLogger("Flows")

PROPOSALS_FILE = "treasury_proposals.json"
FLOWS_FILE = "data/flows.json"
EXTERN = "extern"

# proposal-type -> (status waarin het geld verplaatst IS, van, naar, bedragveld)
_PROPOSAL_FLOWS = {
    "DEPLOY_YIELD": ("DEPLOYED", "swarm", "yield_core", "source_hl"),
    "REBALANCE": ("COMPLETED", "yield_core", "swarm", "amount_usd"),
    "FUND_SLEEVE": ("DEPLOYED", "swarm", "thematic_exposure", "amount_usd"),
    "SLEEVE_REBALANCE": ("DEPLOYED", "thematic_exposure", "swarm", "amount_usd"),
    # Handmatige bridge van de treasury-wallet naar HL; voltooid als het HL-saldo stijgt.
    "FUND_TRADING": ("COMPLETED", "yield_core", "swarm", "amount_usd"),
}
_TS_VELDEN = ("deployed_at", "completed_at", "updated_at", "created_at")

# Statussen waarin kasbeheer geld ONDERWEG heeft. Tijdens zo'n transit klopt geen
# enkel saldo met de boeken; de verliesbewaking slaat de saldo-check dan over.
ONDERWEG_STATUSSEN = {"APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL", "BRIDGED",
                      "REBALANCING", "SWITCHING", "BRIDGE_BACK_NEEDED", "BRIDGING_TO_HL",
                      "MONITORING"}


class FlowsOnleesbaar(Exception):
    """Een bronbestand bestaat maar is niet te lezen. Dan is elk rendement onmeetbaar."""


def _epoch(waarde):
    """ISO-string of epoch -> epoch-seconden (naive = UTC). None als het niet kan."""
    if waarde is None or isinstance(waarde, bool):
        return None
    if isinstance(waarde, (int, float)):
        return float(waarde) if math.isfinite(waarde) else None
    try:
        dt = datetime.fromisoformat(str(waarde).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _lees(pad, standaard):
    """Ontbrekend bestand = standaard (legitiem). Corrupt bestand = luid falen."""
    try:
        with open(pad, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return standaard
    except Exception as e:
        raise FlowsOnleesbaar("%s is niet te lezen: %s" % (pad, e))


def _proposal_lijst(proposals):
    if isinstance(proposals, dict):
        return proposals.get("proposals", list(proposals.values()))
    return proposals or []


def uit_proposals(proposals):
    """Stromen die kasbeheer al heeft uitgevoerd, afgeleid uit zijn proposals."""
    uit = []
    for p in _proposal_lijst(proposals):
        if not isinstance(p, dict):
            continue
        regel = _PROPOSAL_FLOWS.get(p.get("type"))
        if not regel:
            continue
        status, van, naar, veld = regel
        if p.get("status") != status:
            continue
        bedrag = p.get(veld)
        if veld == "source_hl" and bedrag is None:
            bedrag = p.get("amount_usd") if p.get("source") == "hl" else None
        try:
            bedrag = float(bedrag)
        except (TypeError, ValueError):
            continue
        if not (bedrag > 0) or not math.isfinite(bedrag):
            continue
        ts = next((e for e in (_epoch(p.get(v)) for v in _TS_VELDEN) if e is not None), None)
        if ts is None:
            continue
        uit.append({"ts": ts, "van": van, "naar": naar, "bedrag_usd": round(bedrag, 2),
                    "bron": "proposal:%s" % p.get("id")})
    return uit


def kasbeheer_onderweg(proposals):
    """True als kasbeheer op dit moment geld in transit heeft."""
    return any(isinstance(p, dict) and p.get("status") in ONDERWEG_STATUSSEN
               for p in _proposal_lijst(proposals))


def laad_flows(proposals_pad=PROPOSALS_FILE, handmatig_pad=FLOWS_FILE):
    """Alle bekende stromen, oplopend in tijd. Gooit FlowsOnleesbaar bij een corrupte bron."""
    stromen = uit_proposals(_lees(proposals_pad, []))
    for r in (_lees(handmatig_pad, {"flows": []}).get("flows") or []):
        ts = _epoch(r.get("ts"))
        try:
            bedrag = float(r.get("bedrag_usd"))
        except (TypeError, ValueError):
            continue
        if ts is None or not math.isfinite(bedrag) or bedrag <= 0:
            continue
        stromen.append({"ts": ts, "van": r.get("van"), "naar": r.get("naar"),
                        "bedrag_usd": round(bedrag, 2),
                        "bron": "handmatig:%s" % (r.get("omschrijving") or "")})
    stromen.sort(key=lambda f: f["ts"])
    return stromen


def netto_flow(stromen, potje, t0, t1):
    """Netto instroom in `potje` met t0 < ts <= t1. Positief = er kwam geld bij."""
    totaal = 0.0
    for f in stromen:
        if not (t0 < f["ts"] <= t1):
            continue
        if f["naar"] == potje:
            totaal += f["bedrag_usd"]
        if f["van"] == potje:
            totaal -= f["bedrag_usd"]
    return totaal


def boek_flow(van, naar, bedrag_usd, omschrijving, ts=None, pad=FLOWS_FILE):
    """Voeg een stroom toe aan data/flows.json. In-place schrijven: data/ is een bind mount."""
    bedrag = float(bedrag_usd)
    if not math.isfinite(bedrag) or bedrag <= 0:
        raise ValueError("bedrag moet een positief eindig getal zijn, kreeg %r" % bedrag_usd)
    if van == naar:
        raise ValueError("van en naar zijn hetzelfde potje (%s)" % van)
    data = _lees(pad, {"flows": []})
    regel = {
        "ts": datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts is not None
        else datetime.now(timezone.utc).isoformat(),
        "van": van, "naar": naar, "bedrag_usd": round(bedrag, 2),
        "omschrijving": omschrijving,
    }
    data.setdefault("flows", []).append(regel)
    map_ = os.path.dirname(pad)
    if map_:
        os.makedirs(map_, exist_ok=True)
    with open(pad, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return regel
