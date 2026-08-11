"""Post-deploy verificatie: klopt de LÍVE toestand met wat we denken te hebben?

Draait IN de container (`docker exec -w /app`), niet op de dev-machine — dat is het
hele punt. De fouten die dit vangt hadden allemaal groene tests én een geslaagde
deploy, en faalden stil:

  * config/*.json is volume-mounted: de HOST-kopie wint van de image, dus een
    repo-wijziging bereikt productie niet via een rebuild. Twee keer misgegaan op
    2026-08-03; de code las een lege themes-lijst en de allocator-bescherming deed
    stil niets.
  * deploy.ps1 kopieerde lokale state over productie heen, waardoor trade_log
    posities claimde die de beurs niet had.
  * sluit-orders zonder reduceOnly openden posities in plaats van te sluiten.
  * de trader adopteerde posities van de allocator en hing er een stop-loss aan.

Gebruik:
    docker exec -w /app -e PYTHONPATH=/app agent_trader_swarm python3 scripts/verify_live.py

Exit 0 = alles goed, 1 = minstens één check gefaald.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "/app")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    """Registreer een check; een crash telt als FAIL, niet als stille skip."""
    def deco(fn):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"check crashte: {type(e).__name__}: {e}"
        RESULTS.append((name, ok, detail))
        return fn
    return deco


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 1. Config: is de LIVE config bruikbaar (niet leeg/afgekapt)? ─────────────

@check("config/barbell_targets.json heeft thema's")
def _barbell_themes():
    cfg = _load("config/barbell_targets.json")
    themes = cfg.get("themes") or {}
    if not themes:
        return False, ("LEGE themes-lijst — dit is de host-kopie die de image "
                       "overschaduwt. Schrijf de repo-versie in-place naar de host.")
    return True, f"{len(themes)} thema's: {', '.join(sorted(themes))}"


@check("allocator-bescherming actief zolang een brug open staat")
def _allocator_guard():
    from utils.allocator_positions import barbell_bridge_bases
    cfg = _load("config/barbell_targets.json")
    active = [t for t, v in (cfg.get("themes") or {}).items()
              if ((v or {}).get("bridge") or {}).get("active")]
    bases = barbell_bridge_bases()
    if active and not bases:
        return False, (f"brug actief voor {active} maar barbell_bridge_bases() is LEEG — "
                       "de trader zal de positie adopteren en er een stop-loss op zetten")
    if not active:
        return True, "geen actieve brug (niets te beschermen)"
    return True, f"beschermd: {sorted(bases)}"


@check("conviction core config plausibel")
def _conviction():
    cfg = _load("config/conviction_core.json")
    tgt = float(cfg.get("target_usd") or 0)
    if cfg.get("enabled") and tgt <= 0:
        return False, "enabled=true maar target_usd=0 — sleeve doet niets"
    return True, f"enabled={cfg.get('enabled')} target=${tgt:.0f} reserve=${cfg.get('reserve_spot_usdc')}"


@check("treasury allocation config plausibel")
def _treasury_cfg():
    cfg = _load("config/treasury_allocation.json")
    missing = [k for k in ("target_trade_pct", "min_hl_buffer_usd", "rebalance_drift_pct")
               if k not in cfg]
    if missing:
        return False, f"ontbrekende sleutels: {missing}"
    return True, (f"trade_pct={cfg['target_trade_pct']} buffer=${cfg['min_hl_buffer_usd']} "
                  f"drift={cfg['rebalance_drift_pct']}%")


# ── 2. Boek vs beurs: de duurste categorie fouten ───────────────────────────

def _live_positions():
    from utils.exchange_client import HyperliquidExchange
    ex = HyperliquidExchange(testnet=False)
    out = {}
    for p in ex.fetch_all_positions() or []:
        size = (p.get("info") or {}).get("szi") or p.get("contracts") or 0
        try:
            if abs(float(size)) <= 1e-9:
                continue
        except (TypeError, ValueError):
            continue
        base = str(p.get("symbol") or "").split("/")[0].upper()
        out[base] = float(size)
    return out


def _open_trades():
    try:
        trades = _load("trade_log.json")
    except Exception:
        return []
    return [t for t in trades if str(t.get("status", "")).upper() == "OPEN"]


@check("geen spookposities (OPEN in trade_log, niet op de beurs)")
def _phantoms():
    live = _live_positions()
    ghosts = [t.get("id") for t in _open_trades()
              if str(t.get("ticker") or "").split("/")[0].upper() not in live]
    if ghosts:
        return False, (f"{len(ghosts)} OPEN trade(s) zonder positie op de beurs: {ghosts[:5]} — "
                       "sluit-orders hierop worden geweigerd (reduceOnly) en als "
                       "PHANTOM_NO_POSITION weggeboekt")
    return True, f"{len(_open_trades())} open trade(s), allemaal met echte positie"


@check("geen weespositie (op de beurs, niet in het boek en geen allocator)")
def _orphans():
    from utils.allocator_positions import barbell_bridge_bases
    live = _live_positions()
    booked = {str(t.get("ticker") or "").split("/")[0].upper() for t in _open_trades()}
    allocator = barbell_bridge_bases()
    orphans = [b for b in live if b not in booked and b not in allocator]
    if orphans:
        return False, (f"onbeheerde positie(s) op de beurs: {orphans} — geen stop-loss, "
                       "niemand beheert dit (zo ontstonden de orphan-shorts)")
    return True, (f"{len(live)} positie(s): {sorted(booked & set(live)) or '-'} beheerd, "
                  f"{sorted(allocator & set(live)) or '-'} allocator")


@check("allocator-posities staan NIET in trade_log")
def _allocator_not_booked():
    from utils.allocator_positions import barbell_bridge_bases
    bases = barbell_bridge_bases()
    if not bases:
        return True, "geen allocator-posities"
    try:
        trades = _load("trade_log.json")
    except Exception:
        return True, "trade_log onleesbaar (aparte check)"
    bad = [t.get("id") for t in trades
           if str(t.get("ticker") or "").split("/")[0].upper() in bases]
    if bad:
        return False, (f"allocator-positie geadopteerd als trade: {bad} — de "
                       "StrategyManager hangt er een stop-loss aan en sluit de buy-and-hold")
    return True, f"{sorted(bases)} correct buiten het boek gehouden"


# ── 3. Zijn de beschermingen zelf aanwezig in de draaiende code? ────────────

def _app_src(rel: str) -> str:
    """Lees GEDEPLOYDE code altijd uit /app, ongeacht de werkdirectory."""
    with open(os.path.join("/app", rel), encoding="utf-8") as f:
        return f.read()


@check("sluit-orders gebruiken reduceOnly")
def _reduce_only():
    src = _app_src("agents/execution_agent.py")
    n = src.count("reduce_only=True")
    if n < 2:
        return False, (f"maar {n}x reduce_only=True — close_position() en de partial "
                       "exit moeten het allebei meesturen, anders OPENT een sluit-order")
    return True, f"{n} sluit-paden met reduceOnly"


@check("SwarmMonitor brug-vervaldatum-check geregistreerd")
def _check23():
    src = _app_src("agents/swarm_monitor.py")
    if src.count("_check_barbell_bridge_expiry") < 2:
        return False, "check niet gedefinieerd én geregistreerd"
    return True, "Check 23 actief"


@check("state-bestanden zijn bestanden, geen directories")
def _state_files():
    bad = [f for f in ("trade_log.json", "dashboard.json", "active_assets.json",
                       "config/barbell_targets.json", "config/conviction_core.json")
           if os.path.isdir(f)]
    if bad:
        return False, f"DIRECTORY waar een bestand hoort (kapotte bind-mount): {bad}"
    return True, "alle gecontroleerde paden zijn bestanden"


def main() -> int:
    width = max(len(n) for n, _, _ in RESULTS)
    failed = 0
    print("=" * (width + 60))
    print("LIVE VERIFICATIE  (draait in de container, leest de echte toestand)")
    print("=" * (width + 60))
    for name, ok, detail in RESULTS:
        print(f"{'OK  ' if ok else 'FAIL'}  {name:<{width}}  {detail}")
        if not ok:
            failed += 1
    print("-" * (width + 60))
    print(f"{len(RESULTS) - failed}/{len(RESULTS)} checks geslaagd")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
