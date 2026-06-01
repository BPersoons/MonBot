import ccxt
import pandas as pd
import logging
import datetime

class AutoBacktester:
    def __init__(self):
        self.exchange = ccxt.hyperliquid({
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        self.logger = logging.getLogger("AutoBacktester")

    def fetch_historical_data(self, ticker: str, timeframe: str = '1h', days: int = 7, store_ticker: bool = True) -> pd.DataFrame:
        """
        Fetches the last N days of candles for a specific timeframe.
        Expects ticker in clean format (e.g. XYZ-GOLD/USDC or BTC/USDC).
        Adds :USDC suffix required by Hyperliquid perpetual swap API.
        """
        try:
            self.ticker = ticker  # store for asset_class detection in run_comparative_simulation
            hl_ticker = ticker if ticker.endswith(':USDC') else f"{ticker}:USDC"
            since = self.exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
            ohlcv = self.exchange.fetch_ohlcv(hl_ticker, timeframe=timeframe, since=since)

            if not ohlcv:
                return pd.DataFrame()

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            self.logger.warning(f"Hyperliquid missing data for {ticker}, skipping AutoBacktest: {e}")
            return pd.DataFrame()

    def run_simulation(self, df: pd.DataFrame) -> dict:
        """Run standard agent simulation."""
        # Use comparative engine and return agent metrics plus short tracking
        results = self.run_comparative_simulation(df)
        agent_metrics = results.get('agent', {})
        agent_metrics['agent_short'] = results.get('agent_short', {})
        return agent_metrics

    def run_comparative_simulation(self, df: pd.DataFrame, asset_class: str = None) -> dict:
        """
        Run simulations for Agent Strategy vs Benchmarks.
        Returns metrics for: agent, buy_hold, macd, bollinger.

        asset_class overrides auto-detection for the 'agent' strategy signal.
        If omitted, detected from self.ticker (set by fetch_historical_data).
        """
        if df.empty: return {}

        from core.strategy_logic import StrategyLogic

        # Pre-calculate indicators (used by all strategies including agent pre-screen)
        # NOTE: the backtester uses the legacy RSI+EMA signal for candidate surfacing.
        # This is intentional — the ResearchAgent pre-screen needs frequent signals to
        # surface candidates; the new regime-aware strategy is too selective for 7-day
        # backtests and would produce 0 candidates. Actual trading signals come from
        # TechnicalAnalyst.analyze(), not from this backtester.
        indicators = StrategyLogic.calculate_indicators(df['close'].tolist())

        # Helper to run a single pass
        FEE_PCT = 0.0007       # 0.07% per side (Hyperliquid taker)
        SLIPPAGE_PCT = 0.0005  # 0.05% per side: spread + market-impact estimate
        COST_PCT = FEE_PCT + SLIPPAGE_PCT  # 0.12% per side -> 0.24% round-trip
        def simulate_strategy(strategy_name: str, direction: str = 'LONG') -> dict:
            capital = 1000.0
            position = 0.0
            entry_price = 0.0
            roundtrips = []  # Track (entry_price, exit_price) pairs for accurate win rate

            # Start loop after indicators stabilize (first 50 candles)
            start_idx = 50
            if len(df) <= start_idx: return {}

            for i in range(start_idx, len(df)):
                price = df['close'].iloc[i]
                timestamp = df['timestamp'].iloc[i] if 'timestamp' in df.columns else i

                # Context for signal
                current_inds = {k: v.iloc[i] for k, v in indicators.items()}
                prev_inds = {k: v.iloc[i-1] for k, v in indicators.items()}

                # Get Signal
                signal = 0.0
                if strategy_name == 'agent':
                    s, _ = StrategyLogic.get_agent_signal(price, current_inds)
                    signal = 1.0 if s > 0.3 else (-1.0 if s < -0.3 else 0.0)
                elif strategy_name == 'macd':
                    signal = StrategyLogic.get_macd_signal(current_inds, prev_inds)
                elif strategy_name == 'bollinger':
                    signal = StrategyLogic.get_bollinger_signal(price, current_inds)
                elif strategy_name == 'buy_hold':
                    if i == start_idx: signal = 1.0  # Buy at start
                    elif i == len(df)-1: signal = -1.0  # Sell at end

                # Execute with cost (fee + slippage) deduction
                if direction == 'LONG':
                    if signal > 0 and position == 0:
                        cost = capital * COST_PCT
                        capital -= cost
                        position = capital / price
                        entry_price = price
                        capital = 0
                    elif signal < 0 and position > 0:
                        exit_notional = position * price
                        cost = exit_notional * COST_PCT
                        capital = exit_notional - cost
                        roundtrips.append((entry_price, price))
                        position = 0
                elif direction == 'SHORT':
                    if signal < 0 and position == 0:
                        cost = capital * COST_PCT
                        capital -= cost
                        position = capital / price
                        entry_price = price
                        capital = 0
                    elif signal > 0 and position > 0:
                        profit = position * (entry_price - price)
                        # Cost is on buyback notional (position * exit_price), NOT on gross.
                        # Previous code charged fee on (entry_notional + profit) which over-
                        # charged winning shorts and under-charged losing shorts.
                        exit_notional = position * price
                        cost = exit_notional * COST_PCT
                        capital = (position * entry_price) + profit - cost
                        roundtrips.append((entry_price, price))
                        position = 0

            # Close position at end
            if position > 0:
                end_price = df['close'].iloc[-1]
                if direction == 'LONG':
                    exit_notional = position * end_price
                    cost = exit_notional * COST_PCT
                    capital = exit_notional - cost
                    roundtrips.append((entry_price, end_price))
                elif direction == 'SHORT':
                    profit = position * (entry_price - end_price)
                    exit_notional = position * end_price
                    cost = exit_notional * COST_PCT
                    capital = (position * entry_price) + profit - cost
                    roundtrips.append((entry_price, end_price))

            # Calc metrics
            initial_capital = 1000.0
            pnl_pct = ((capital - initial_capital) / initial_capital) * 100

            # Win rate + per-trade R metrics from tracked roundtrips
            total_roundtrips = len(roundtrips)
            wins, losses = [], []
            for entry_p, exit_p in roundtrips:
                if direction == 'LONG':
                    pnl_pct_trade = (exit_p - entry_p) / entry_p * 100.0
                else:  # SHORT
                    pnl_pct_trade = (entry_p - exit_p) / entry_p * 100.0
                if pnl_pct_trade > 0: wins.append(pnl_pct_trade)
                elif pnl_pct_trade < 0: losses.append(abs(pnl_pct_trade))

            win_rate = len(wins) / total_roundtrips if total_roundtrips > 0 else 0.0
            avg_win_pct  = sum(wins) / len(wins) if wins else 0.0
            avg_loss_pct = sum(losses) / len(losses) if losses else 0.0

            # Risk-reward AFTER round-trip cost (fee + slippage). Subtracts the
            # per-trade cost drag from wins and adds it to losses, giving an
            # honest realised R that gates marginal strategies.
            rt_cost_pct = COST_PCT * 200.0  # round-trip in pct
            adj_win  = max(0.0, avg_win_pct - rt_cost_pct)
            adj_loss = avg_loss_pct + rt_cost_pct
            if adj_loss > 0:
                rr_after_costs = adj_win / adj_loss
            else:
                rr_after_costs = 999.0 if adj_win > 0 else 0.0

            return {
                'final_capital': round(capital, 2),
                'total_pnl_pct': round(pnl_pct, 2),
                'trades': total_roundtrips,
                'win_rate': round(win_rate, 2),
                'avg_win_pct': round(avg_win_pct, 3),
                'avg_loss_pct': round(avg_loss_pct, 3),
                'rr_after_costs': round(rr_after_costs, 2),
            }

        return {
            'agent': simulate_strategy('agent', 'LONG'),
            'agent_short': simulate_strategy('agent', 'SHORT'),
            'buy_hold': simulate_strategy('buy_hold', 'LONG'),
            'macd': simulate_strategy('macd', 'LONG'),
            'bollinger': simulate_strategy('bollinger', 'LONG')
        }
