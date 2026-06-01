"""
shadow_veto_analysis.py — Analyze hypothetical P&L of risk-vetoed trades.

Reads decision_history.json (from container or local) and identifies trades
that passed the council (BUILD_CASE) but were blocked by the Risk Manager.
Fetches current prices to calculate what would have happened.

Usage:
    # Copy decision_history from container first:
    gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b \
        --command='sudo docker cp agent_trader_swarm:/app/decision_history.json /tmp/dh.json && cat /tmp/dh.json' \
        > /tmp/decision_history.json

    python scripts/shadow_veto_analysis.py [--file /tmp/decision_history.json] [--hours 24]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root so we can import exchange_client if needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_history(path: str) -> list:
    with open(path) as f:
        return json.load(f)


def filter_vetoed_trades(history: list, hours: float = None) -> list:
    """Filter for BUILD_CASE decisions that were risk-vetoed."""
    vetoed = []
    cutoff = None
    if hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    for entry in history:
        # A risk-vetoed BUILD_CASE has risk_status=RISK_VETO
        # OR: decision=BUILD_CASE but reason contains "Risk Veto"
        is_veto = (
            entry.get("risk_status") == "RISK_VETO"
            or "Risk Veto" in (entry.get("reason") or "")
        )
        if not is_veto:
            continue

        # Must have a valid price
        price = entry.get("current_price", 0)
        if not price or price <= 0:
            continue

        # Time filter
        if cutoff:
            try:
                ts = datetime.fromisoformat(entry["timestamp"]).replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
            except (ValueError, KeyError):
                continue

        vetoed.append(entry)

    return vetoed


def fetch_current_prices(tickers: list) -> dict:
    """Fetch current prices for a list of tickers via CCXT."""
    try:
        import ccxt
        hl = ccxt.hyperliquid({"walletAddress": "0x0000000000000000000000000000000000000000"})
        hl.load_markets()
        prices = {}
        for ticker in tickers:
            try:
                t = hl.fetch_ticker(ticker)
                prices[ticker] = t.get("last") or t.get("close") or 0
            except Exception:
                pass
        return prices
    except ImportError:
        print("WARNING: ccxt not installed, cannot fetch live prices")
        return {}


def analyze(vetoed: list, current_prices: dict, position_size_usd: float = 50.0):
    """Calculate hypothetical P&L for each vetoed trade."""
    results = []
    for entry in vetoed:
        ticker = entry["ticker"]
        veto_price = entry["current_price"]
        direction = entry.get("direction", "LONG")
        score = entry.get("score", 0)
        sl_pct = entry.get("stop_loss_pct", 5.0)
        timestamp = entry.get("timestamp", "?")

        now_price = current_prices.get(ticker)
        if not now_price:
            continue

        # Hypothetical position size
        qty = position_size_usd / veto_price
        if direction == "LONG":
            pnl = (now_price - veto_price) * qty
            pnl_pct = ((now_price - veto_price) / veto_price) * 100
        else:
            pnl = (veto_price - now_price) * qty
            pnl_pct = ((veto_price - now_price) / veto_price) * 100

        # Would SL have been hit? (simplified: no trailing, just initial SL)
        if direction == "LONG":
            sl_price = veto_price * (1 - sl_pct / 100)
        else:
            sl_price = veto_price * (1 + sl_pct / 100)

        results.append({
            "ticker": ticker,
            "timestamp": timestamp,
            "direction": direction,
            "score": score,
            "veto_price": round(veto_price, 6),
            "current_price": round(now_price, 6),
            "sl_price": round(sl_price, 6),
            "hyp_pnl_usd": round(pnl, 2),
            "hyp_pnl_pct": round(pnl_pct, 2),
            "position_usd": position_size_usd,
        })

    return results


def print_report(results: list, vetoed_total: int):
    if not results:
        print(f"\nNo vetoed trades with matchable current prices (total vetoed: {vetoed_total})")
        return

    print(f"\n{'='*80}")
    print(f"  SHADOW VETO ANALYSIS — {len(results)} trades analyzed (of {vetoed_total} vetoed)")
    print(f"{'='*80}\n")

    # Summary stats
    total_pnl = sum(r["hyp_pnl_usd"] for r in results)
    wins = [r for r in results if r["hyp_pnl_usd"] > 0]
    losses = [r for r in results if r["hyp_pnl_usd"] <= 0]
    win_rate = len(wins) / len(results) * 100 if results else 0

    print(f"  Hypothetical Total P&L:  ${total_pnl:+.2f}")
    print(f"  Win Rate:                {win_rate:.0f}% ({len(wins)}W / {len(losses)}L)")
    if wins:
        print(f"  Avg Win:                 ${sum(r['hyp_pnl_usd'] for r in wins)/len(wins):+.2f}")
    if losses:
        print(f"  Avg Loss:                ${sum(r['hyp_pnl_usd'] for r in losses)/len(losses):+.2f}")
    print()

    # Per-ticker breakdown
    tickers = {}
    for r in results:
        tk = r["ticker"]
        if tk not in tickers:
            tickers[tk] = {"count": 0, "pnl": 0, "scores": []}
        tickers[tk]["count"] += 1
        tickers[tk]["pnl"] += r["hyp_pnl_usd"]
        tickers[tk]["scores"].append(r["score"])

    print(f"  {'Ticker':<20} {'Count':>5} {'Hyp P&L':>10} {'Avg Score':>10}")
    print(f"  {'-'*20} {'-'*5} {'-'*10} {'-'*10}")
    for tk, data in sorted(tickers.items(), key=lambda x: x[1]["pnl"], reverse=True):
        avg_score = sum(data["scores"]) / len(data["scores"])
        print(f"  {tk:<20} {data['count']:>5} ${data['pnl']:>+9.2f} {avg_score:>10.2f}")

    # Top 5 best and worst
    by_pnl = sorted(results, key=lambda r: r["hyp_pnl_usd"], reverse=True)
    print(f"\n  Top 5 missed gains:")
    for r in by_pnl[:5]:
        print(f"    {r['ticker']:15} {r['direction']:5} score={r['score']:.2f} "
              f"entry=${r['veto_price']:.4f} now=${r['current_price']:.4f} "
              f"P&L=${r['hyp_pnl_usd']:+.2f} ({r['hyp_pnl_pct']:+.1f}%)")

    print(f"\n  Top 5 avoided losses:")
    for r in by_pnl[-5:]:
        print(f"    {r['ticker']:15} {r['direction']:5} score={r['score']:.2f} "
              f"entry=${r['veto_price']:.4f} now=${r['current_price']:.4f} "
              f"P&L=${r['hyp_pnl_usd']:+.2f} ({r['hyp_pnl_pct']:+.1f}%)")

    print(f"\n{'='*80}")


def main():
    parser = argparse.ArgumentParser(description="Analyze hypothetical P&L of risk-vetoed trades")
    parser.add_argument("--file", default="decision_history.json", help="Path to decision_history.json")
    parser.add_argument("--hours", type=float, default=None, help="Only analyze last N hours")
    parser.add_argument("--size", type=float, default=50.0, help="Hypothetical position size in USD (default: 50)")
    args = parser.parse_args()

    history = load_history(args.file)
    print(f"Loaded {len(history)} decision history entries from {args.file}")

    vetoed = filter_vetoed_trades(history, hours=args.hours)
    print(f"Found {len(vetoed)} risk-vetoed trades" + (f" in last {args.hours}h" if args.hours else ""))

    if not vetoed:
        print("No vetoed trades found. Nothing to analyze.")
        return

    # Deduplicate tickers
    tickers = list(set(v["ticker"] for v in vetoed))
    print(f"Fetching current prices for {len(tickers)} tickers...")
    current_prices = fetch_current_prices(tickers)
    print(f"Got prices for {len(current_prices)} tickers")

    results = analyze(vetoed, current_prices, position_size_usd=args.size)
    print_report(results, len(vetoed))


if __name__ == "__main__":
    main()
