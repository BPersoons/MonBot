#!/usr/bin/env python3
"""
Conviction Barbell — rebalance-rekenhulp (broker-route).

Leest je actuele posities (USD-waardes) in, past de mechanische banden + cooldown toe,
en zegt precies wat te kopen/verkopen om terug binnen de banden te komen. Plaatst ZELF
GEEN orders — puur advies. Jij voert de paar trades handmatig uit bij je broker.

Zie docs/CONVICTION_BARBELL_PLAN.md voor de strategie en de regels.

Gebruik (lokaal, geen internet nodig):
    # 1. eenmalig: kopieer template en vul je actuele waardes in
    cp barbell_holdings.example.json barbell_holdings.json   # (Windows: copy)
    # 2. draai de rekenhulp
    python scripts/rebalance_calculator.py
    # 3. na uitvoeren van geadviseerde trades: stempel de cooldown
    python scripts/rebalance_calculator.py --executed BTC,QQQ

Alle bedragen zijn in USD. De rekenhulp heeft GEEN prijzen nodig: je leest de actuele
waardes af bij je broker/treasury en de output is ook in USD (brokers laten je kopen
voor een bedrag). Zo kan het script nooit stuklopen op een prijs-API.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

try:  # Windows-console compat (project-conventie)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TARGETS = os.path.join(_ROOT, "config", "barbell_targets.json")
_HOLDINGS = os.path.join(_ROOT, "barbell_holdings.json")
_LOG = os.path.join(_ROOT, "barbell_rebalance_log.json")


def _load_json(path: str, what: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"FOUT: {what} niet gevonden op {path}", file=sys.stderr)
        if path == _HOLDINGS:
            print("Kopieer barbell_holdings.example.json naar barbell_holdings.json "
                  "en vul je actuele waardes in.", file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, OSError) as e:
        print(f"FOUT: kan {what} niet lezen ({e})", file=sys.stderr)
        sys.exit(1)


def _save_log(log: dict) -> None:
    try:
        with open(_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
    except OSError as e:
        print(f"WAARSCHUWING: kon cooldown-log niet opslaan ({e})", file=sys.stderr)


def _days_since(iso_date: str) -> float:
    try:
        d = _dt.date.fromisoformat(iso_date)
    except (ValueError, TypeError):
        return 1e9
    return (_dt.date.today() - d).days


def _in_cooldown(asset: str, log: dict, cooldown_days: int) -> float | None:
    last = (log.get("last_action") or {}).get(asset)
    if not last:
        return None
    elapsed = _days_since(last)
    if elapsed < cooldown_days:
        return cooldown_days - elapsed
    return None


def _fmt(usd: float) -> str:
    return f"${usd:,.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Conviction Barbell rebalance-rekenhulp")
    ap.add_argument("--executed", type=str, default="",
                    help="Comma-sep lijst van assets waarvan je zojuist de trade "
                         "hebt uitgevoerd; stempelt vandaag als cooldown-start.")
    args = ap.parse_args()

    cfg = _load_json(_TARGETS, "targets-config")
    log = {}
    if os.path.exists(_LOG):
        log = _load_json(_LOG, "cooldown-log")

    # --- cooldown stempelen en stoppen ---
    if args.executed.strip():
        stamp = _dt.date.today().isoformat()
        log.setdefault("last_action", {})
        for a in [x.strip().upper() for x in args.executed.split(",") if x.strip()]:
            log["last_action"][a] = stamp
        _save_log(log)
        print(f"Cooldown gestempeld ({stamp}) voor: {args.executed.upper()}")
        return

    holdings = _load_json(_HOLDINGS, "holdings")
    bands = cfg["bands"]
    targets_pct = cfg["growth_targets_pct"]
    cooldown_days = int(bands.get("cooldown_days", 7))
    min_trade = float(bands.get("min_trade_usd", 25))

    safe_usd = float(holdings.get("safe_usd", 0) or 0)
    growth = {k.upper(): float(v or 0) for k, v in holdings.get("growth_usd", {}).items()}
    growth_usd = sum(growth.values())
    total = safe_usd + growth_usd

    if total <= 0:
        print("FOUT: totale portefeuille is 0. Vul barbell_holdings.json.", file=sys.stderr)
        sys.exit(1)

    print("=" * 64)
    print("  CONVICTION BARBELL - rebalance-check   "
          f"({_dt.date.today().isoformat()})")
    print("=" * 64)
    print(f"  Totaal:        {_fmt(total)}")
    print(f"  Veilig (yield):{_fmt(safe_usd):>14}  ({safe_usd/total*100:5.1f}%  "
          f"target {cfg['safe_pct']}%)")
    print(f"  Groei-mandje:  {_fmt(growth_usd):>14}  ({growth_usd/total*100:5.1f}%  "
          f"target {cfg['growth_pct']}%)")
    print("-" * 64)

    actions: list[str] = []
    traded_assets: set[str] = set()
    net_flow = 0.0  # +/- USD; som van act, >0 = groei groeit (uit veilig), <0 = naar veilig

    trim_mult = float(bands["trim_mult"])
    add_mult = float(bands["add_mult"])
    cap_pct = float(bands["hard_cap_pct_of_growth"])

    # ---------- 1. TOP-LEVEL 70/30: bepaal doelgrootte groei-pool ----------
    growth_frac = growth_usd / total * 100
    hi = float(bands["toplevel_high_pct"])
    lo = float(bands["toplevel_low_pct"])
    resize = growth_frac > hi or growth_frac < lo
    pool_target = (cfg["growth_pct"] / 100 * total) if resize else growth_usd

    print(f"  [1] TOP-LEVEL {int(cfg['safe_pct'])}/{int(cfg['growth_pct'])}")
    if resize:
        richting = "verklein" if growth_usd > pool_target else "vergroot"
        print(f"      ! Groei = {growth_frac:.1f}% buiten band [{lo:.0f}-{hi:.0f}%] "
              f"-> {richting} pool naar {_fmt(pool_target)} (30% van totaal).")
        print(f"        Alle posities gaan naar target% van de NIEUWE pool (zie stap 2);")
        print(f"        het netto-verschil beweegt tussen groei en veilig.")
    else:
        print(f"      OK - groei {growth_frac:.1f}% binnen band [{lo:.0f}-{hi:.0f}%]; "
              f"pool blijft {_fmt(growth_usd)}.")
    print("-" * 64)

    # ---------- 2. BINNEN GROEI-MANDJE (banden per positie, o.b.v. pool_target) ----------
    print("  [2] BINNEN GROEI-MANDJE (banden per positie)")
    print(f"      {'Positie':<8}{'Waarde':>12}{'Nu%':>8}{'Target%':>9}{'Status':>16}")

    for asset, tgt_pct in targets_pct.items():
        asset = asset.upper()
        val = growth.get(asset, 0.0)
        cur_pct = (val / growth_usd * 100) if growth_usd else 0.0
        tgt_usd = tgt_pct / 100 * pool_target  # target% van de (evt. herschaalde) pool
        hi_pct = tgt_pct * trim_mult
        lo_pct = tgt_pct * add_mult

        # trigger: pool herschaald, of positie buiten eigen band/cap
        if cur_pct > cap_pct:
            status, reason, trigger = f">CAP {cap_pct:.0f}%", f"boven harde cap {cap_pct:.0f}%", True
        elif cur_pct > hi_pct:
            status, reason, trigger = ">band", f"boven {hi_pct:.0f}% band", True
        elif cur_pct < lo_pct:
            status, reason, trigger = "<band", f"onder {lo_pct:.0f}% band", True
        elif resize:
            status, reason, trigger = "resize", f"pool herschaald naar {int(cfg['growth_pct'])}%", True
        else:
            status, reason, trigger = "OK", "", False

        print(f"      {asset:<8}{_fmt(val):>12}{cur_pct:>7.1f}%{tgt_pct:>8.0f}%"
              f"{status:>16}")

        if not trigger:
            continue
        trade = tgt_usd - val  # >0 = koop, <0 = verkoop
        if abs(trade) < min_trade:
            continue  # te klein om te handelen
        cd = _in_cooldown(asset, log, cooldown_days)
        kind = "KOOP" if trade > 0 else "VERKOOP"
        if cd is not None:
            actions.append(f"[COOLDOWN {cd:.0f}d] {kind} {_fmt(abs(trade))} {asset} "
                           f"({reason}) - nog niet handelen.")
        else:
            actions.append(f"{kind} {_fmt(abs(trade))} {asset}  ({reason})")
            traded_assets.add(asset)
            net_flow += trade

    print("=" * 64)

    # ---------- ACTIES ----------
    print("  ACTIES")
    if not actions:
        print("      Niets te doen - alles binnen de banden.")
    else:
        for i, a in enumerate(actions, 1):
            print(f"      {i}. {a}")
        # netto geld-stroom groei <-> veilig, consistent met bovenstaande trades
        if net_flow < -min_trade:
            print(f"      => NETTO: verplaats {_fmt(-net_flow)} van GROEI -> VEILIG (yield).")
        elif net_flow > min_trade:
            print(f"      => NETTO: haal {_fmt(net_flow)} uit VEILIG -> GROEI (broker).")
        if traded_assets:
            print()
            print("      Na uitvoeren, stempel de cooldown:")
            traded = ",".join(sorted(traded_assets))
            print(f"        python scripts/rebalance_calculator.py --executed {traded}")
    print("=" * 64)


if __name__ == "__main__":
    main()
