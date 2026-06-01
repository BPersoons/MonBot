"""
Post-mortem analysis of current open positions.

Fetches OHLCV from entry → now, computes per-position stats, benchmarks against
BTC, simulates inverse (short) P&L, finds the earliest warning signal, and asks
Gemini for a root-cause narrative.

Usage:
    python scripts/market_retrospective.py          # run once manually
    /loop 4h python scripts/market_retrospective.py # during active dev session

Saves: retrospective_YYYYMMDD.json
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone

BASE_DIR = "/app" if os.path.exists("/app/main.py") else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("MarketRetrospective")

# Load secrets (GCP Secret Manager → .env.adk fallback)
try:
    from utils.gcp_secrets import get_all_trading_secrets
    secrets = get_all_trading_secrets()
    for k, v in secrets.items():
        if v:
            os.environ[k] = v
except Exception as e:
    logger.warning(f"Could not load GCP secrets, falling back to env: {e}")
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, ".env.adk"))
    except Exception:
        pass

TRADE_LOG = os.path.join(BASE_DIR, "trade_log.json")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _load_open_trades() -> list:
    try:
        with open(TRADE_LOG, "r", encoding="utf-8") as f:
            trades = json.load(f)
        return [t for t in trades if t.get("status") == "OPEN"]
    except Exception as e:
        logger.error(f"Could not load {TRADE_LOG}: {e}")
        return []


def _fetch_ohlcv(exchange, ticker: str, since_ms: int, timeframe: str = "1h") -> list:
    """Fetch OHLCV candles from since_ms until now. Returns list of [ts, o, h, l, c, v]."""
    try:
        # Normalize symbol for Hyperliquid
        symbol = ticker
        if "/" not in ticker:
            symbol = f"{ticker}/USDC:USDC"
        elif not ticker.endswith(":USDC"):
            symbol = ticker + ":USDC" if "/USDC" in ticker else ticker

        all_candles = []
        limit = 500
        fetch_since = since_ms
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        while fetch_since < now_ms:
            candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=fetch_since, limit=limit)
            if not candles:
                break
            all_candles.extend(candles)
            last_ts = candles[-1][0]
            if last_ts <= fetch_since or len(candles) < limit:
                break
            fetch_since = last_ts + 1

        return all_candles
    except Exception as e:
        logger.warning(f"OHLCV fetch failed for {ticker} ({timeframe}): {e}")
        return []


def _analyze_position(candles: list, entry_price: float, direction: str) -> dict:
    """Compute per-position stats from 1h candles."""
    if not candles or entry_price <= 0:
        return {}

    closes = [c[4] for c in candles]
    last_price = closes[-1]

    price_change = (last_price - entry_price) / entry_price
    pnl_pct = price_change if direction.upper() == "LONG" else -price_change

    # Max drawdown from entry (worst intra-position close vs entry)
    if direction.upper() == "LONG":
        worst = min(closes)
        max_drawdown = (entry_price - worst) / entry_price * 100
    else:
        worst = max(closes)
        max_drawdown = (worst - entry_price) / entry_price * 100

    # First candle where close dropped below entry * 0.99 (reversal candle)
    reversal_candle = None
    for c in candles:
        close = c[4]
        if direction.upper() == "LONG" and close < entry_price * 0.99:
            reversal_candle = datetime.utcfromtimestamp(c[0] / 1000).isoformat()
            break
        elif direction.upper() == "SHORT" and close > entry_price * 1.01:
            reversal_candle = datetime.utcfromtimestamp(c[0] / 1000).isoformat()
            break

    return {
        "current_price": round(last_price, 6),
        "pnl_pct": round(pnl_pct * 100, 2),
        "inverse_pnl_pct": round(-pnl_pct * 100, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "reversal_candle": reversal_candle,
        "candles_analyzed": len(candles),
    }


def _find_btc_warning(exchange, since_ms: int) -> dict:
    """Find when BTC 4h price first crossed below its 20-period SMA after since_ms."""
    try:
        candles = _fetch_ohlcv(exchange, "BTC/USDC:USDC", since_ms, timeframe="4h")
        if len(candles) < 20:
            return {"warning": "insufficient data"}

        closes = [c[4] for c in candles]
        timestamps = [c[0] for c in candles]

        # Start from candle 20 so we have a full SMA window
        for i in range(20, len(closes)):
            sma20 = sum(closes[i - 20:i]) / 20
            if closes[i] < sma20:
                ts = datetime.utcfromtimestamp(timestamps[i] / 1000).isoformat()
                return {
                    "first_below_sma20_at": ts,
                    "btc_price_then": round(closes[i], 2),
                    "sma20_then": round(sma20, 2),
                    "candles_into_trade": i,
                }

        return {"warning": "BTC never crossed below SMA20 in this window"}
    except Exception as e:
        return {"warning": f"BTC SMA check failed: {e}"}


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def run():
    from utils.exchange_client import HyperliquidExchange

    hl = HyperliquidExchange(testnet=False)
    exchange = hl.public_client
    if not exchange:
        logger.error("Exchange client unavailable — aborting.")
        return

    trades = _load_open_trades()
    if not trades:
        logger.warning("No OPEN trades found in trade_log.json.")
        return

    logger.info(f"Analyzing {len(trades)} open positions...")

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    results = []
    portfolio_pnl_pcts = []

    # Find earliest entry time for BTC benchmark window
    earliest_entry_ms = now_ms
    for t in trades:
        entry_time = t.get("entry_time") or t.get("timestamp", "")
        if entry_time:
            try:
                dt = datetime.fromisoformat(entry_time.replace("Z", "+00:00"))
                ts_ms = int(dt.timestamp() * 1000)
                if ts_ms < earliest_entry_ms:
                    earliest_entry_ms = ts_ms
            except Exception:
                pass

    for trade in trades:
        ticker = trade.get("ticker", "")
        entry_price = float(trade.get("entry_price") or trade.get("price") or 0)
        direction = trade.get("direction", "LONG").upper()
        entry_time_str = trade.get("entry_time") or trade.get("timestamp", "")

        entry_ms = earliest_entry_ms
        if entry_time_str:
            try:
                dt = datetime.fromisoformat(entry_time_str.replace("Z", "+00:00"))
                entry_ms = int(dt.timestamp() * 1000)
            except Exception:
                pass

        logger.info(f"  {ticker} {direction} @ {entry_price}")
        candles = _fetch_ohlcv(exchange, ticker, entry_ms, timeframe="1h")
        stats = _analyze_position(candles, entry_price, direction)

        if stats:
            portfolio_pnl_pcts.append(stats["pnl_pct"])

        results.append({
            "ticker": ticker,
            "direction": direction,
            "entry_price": entry_price,
            "entry_time": entry_time_str,
            "pnl_usd": round(float(trade.get("pnl") or 0), 2),
            **stats,
        })

    # BTC benchmark
    btc_candles = _fetch_ohlcv(exchange, "BTC/USDC:USDC", earliest_entry_ms, timeframe="1h")
    btc_entry = btc_candles[0][4] if btc_candles else 0
    btc_now = btc_candles[-1][4] if btc_candles else 0
    btc_pnl_pct = round((btc_now - btc_entry) / btc_entry * 100, 2) if btc_entry else 0

    avg_portfolio_pnl = round(sum(portfolio_pnl_pcts) / len(portfolio_pnl_pcts), 2) if portfolio_pnl_pcts else 0
    positions_in_loss = sum(1 for p in portfolio_pnl_pcts if p < 0)
    macro_event = positions_in_loss / len(portfolio_pnl_pcts) > 0.75 if portfolio_pnl_pcts else False

    # BTC 4h SMA warning
    btc_warning = _find_btc_warning(exchange, earliest_entry_ms)

    # LLM synthesis
    llm_summary = _generate_llm_summary(results, btc_pnl_pct, avg_portfolio_pnl, macro_event, btc_warning)

    report = {
        "generated_at": datetime.now().isoformat(),
        "positions_analyzed": len(results),
        "positions_in_loss": positions_in_loss,
        "avg_portfolio_pnl_pct": avg_portfolio_pnl,
        "btc_pnl_pct_same_window": btc_pnl_pct,
        "macro_event": macro_event,
        "btc_early_warning": btc_warning,
        "what_if_all_short_avg_pnl_pct": round(-avg_portfolio_pnl, 2),
        "positions": results,
        "llm_summary": llm_summary,
    }

    # Save
    filename = f"retrospective_{datetime.now().strftime('%Y%m%d')}.json"
    out_path = os.path.join(BASE_DIR, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Print human-readable summary
    print("\n" + "=" * 60)
    print(f"MARKET RETROSPECTIVE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print(f"Positions analyzed : {len(results)}")
    print(f"Positions in loss  : {positions_in_loss}/{len(results)}")
    print(f"Avg portfolio P&L  : {avg_portfolio_pnl:+.2f}%")
    print(f"BTC P&L same window: {btc_pnl_pct:+.2f}%")
    print(f"Macro event        : {'YES — correlated sell-off' if macro_event else 'NO — asset-specific'}")
    print(f"What-if SHORT P&L  : {-avg_portfolio_pnl:+.2f}%")
    if btc_warning.get("first_below_sma20_at"):
        print(f"BTC warning signal : {btc_warning['first_below_sma20_at']} "
              f"(price {btc_warning.get('btc_price_then', '?')} crossed below SMA20 "
              f"{btc_warning.get('sma20_then', '?')})")
    print()
    print("Per-position breakdown:")
    for r in sorted(results, key=lambda x: x.get("pnl_pct", 0)):
        pnl = r.get("pnl_pct", 0)
        dd = r.get("max_drawdown_pct", 0)
        rev = r.get("reversal_candle", "none")
        print(f"  {r['ticker']:<12} {r['direction']:<5} "
              f"entry {r['entry_price']:>10.4f}  P&L {pnl:>+7.2f}%  "
              f"MaxDD {dd:.1f}%  reversal {rev}")
    if llm_summary:
        print()
        print("LLM Root-Cause Analysis:")
        print(llm_summary)
    print()
    print(f"Full report saved to: {out_path}")
    print("=" * 60)

    return report


def _generate_llm_summary(results, btc_pnl_pct, avg_pnl, macro_event, btc_warning) -> str:
    try:
        from utils.llm_client import LLMClient
        llm = LLMClient()
    except Exception as e:
        return f"LLM not available: {e}"

    top_losers = sorted(results, key=lambda x: x.get("pnl_pct", 0))[:5]
    losers_text = "\n".join(
        f"  {r['ticker']} {r['direction']}: {r.get('pnl_pct', 0):+.2f}% "
        f"(MaxDD {r.get('max_drawdown_pct', 0):.1f}%, reversal at {r.get('reversal_candle', 'n/a')})"
        for r in top_losers
    )

    btc_warn_text = (
        f"BTC 4h crossed below SMA20 at {btc_warning.get('first_below_sma20_at', 'unknown')} "
        f"(price {btc_warning.get('btc_price_then', '?')} vs SMA {btc_warning.get('sma20_then', '?')})"
        if btc_warning.get("first_below_sma20_at") else "BTC did not cross below SMA20 in this window"
    )

    prompt = f"""You are a trading post-mortem analyst. The swarm opened {len(results)} long positions
that are now underwater. Provide a concise root-cause analysis (4-6 sentences) and specific
recommendations for the next trading cycle.

PORTFOLIO CONTEXT:
- Average portfolio P&L: {avg_pnl:+.2f}%
- BTC P&L over same window: {btc_pnl_pct:+.2f}%
- Macro event (>75% positions correlated): {'YES' if macro_event else 'NO'}
- What-if all SHORT: {-avg_pnl:+.2f}% avg P&L
- Early warning: {btc_warn_text}

WORST POSITIONS:
{losers_text}

Focus on: (1) Was this predictable? (2) What signals existed? (3) What should the swarm do differently?
Be specific and actionable."""

    try:
        return llm.analyze_text(prompt, agent_name="MarketRetrospective").strip()
    except Exception as e:
        return f"LLM synthesis failed: {e}"


if __name__ == "__main__":
    run()
