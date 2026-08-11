"""Welke HL-posities zijn van de ALLOCATOR en niet van de TRADER?

De barbell (docs/CONVICTION_BARBELL_PLAN.md) houdt buy-and-hold-dragers aan op
dezelfde wallet als de trading-swarm. Die posities horen bewust NIET in
`trade_log.json`: ze hebben hun eigen band-logica en geen stop-loss.

Zonder deze uitzondering adopteren twee onafhankelijke paden ze alsnog —
`ExecutionAgent._sync_positions_on_startup()` (id-prefix `HL_OPEN_`) en de
ghost-reconcile in `main.py` (prefix `RECOVERED_`) — en geven ze een standaard
stop-loss mee. StrategyManager sluit de positie dan bij de eerste normale dip.
Dat is exact wat er op 2026-08-03 gebeurde met de XYZ-SMH-brug, minuten na het
openen. Zelfde klasse fout als de twee orphan-shorts: twee systemen die dezelfde
wallet beheren zonder van elkaar te weten.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger("AllocatorPositions")

_CONFIG = "config/barbell_targets.json"


def barbell_bridge_bases() -> set[str]:
    """Bases (bv. {"XYZ-SMH"}) die de allocator aanhoudt via een ACTIEVE brug.

    Leeg zodra `bridge.active` op false gaat — dan mag de trader weer normaal
    reconcilen. Faalt fail-open (lege set) zodat een kapotte config nooit de
    positie-synchronisatie van de swarm blokkeert.
    """
    try:
        with open(_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        logger.debug(f"barbell_bridge_bases: config onleesbaar ({e})")
        return set()

    bases: set[str] = set()
    for theme in (cfg.get("themes") or {}).values():
        bridge = (theme or {}).get("bridge") or {}
        if not bridge.get("active"):
            continue
        inst = str(bridge.get("instrument") or "").strip().upper()
        if inst:
            bases.add(inst.split("/")[0])
    return bases


def is_allocator_position(ticker: str) -> bool:
    """True als dit ticker door de allocator wordt aangehouden."""
    if not ticker:
        return False
    return str(ticker).split("/")[0].upper() in barbell_bridge_bases()
