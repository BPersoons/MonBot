import ccxt
import pandas as pd
import logging
import datetime

class AutoBacktester:
    def __init__(self):
        self.exchange = ccxt.binance()
        self.logger = logging.getLogger("AutoBacktester")

    def fetch_historical_data(self, ticker: str, timeframe: str = '1h', days: int = 7) -> pd.DataFrame:
        """
        Fetches the last N days of candles for a specific timeframe.
        """
        try:
            since = self.exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
            ohlcv = self.exchange.fetch_ohlcv(ticker, timeframe=timeframe, since=since)
            
            if not ohlcv:
                return pd.DataFrame()

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            self.logger.warning(f"Binance missing data for {ticker}, skipping AutoBacktest: {e}")
            return pd.DataFrame()

    def run_simulation(self, df: pd.DataFrame) -> dict:
        """Run standard agent simulation."""
        # Use comparative engine and return agent metrics plus short tracking
        results = self.run_comparative_simulation(df)
        agent_metrics = results.get('agent', {})
        agent_metrics['agent_short'] = results.get('agent_short', {})
        return agent_metrics

    def run_comparative_simulation(self, df: pd.DataFrame) -> dict:
        """
        Run simulations for Agent Strategy vs Benchmarks.
        Returns metrics for: agent, buy_hold, macd, bollinger.
        """
        if df.empty: return {}
        
        # Pre-calculate indicators
        from core.strategy_logic import StrategyLogic
        indicators = StrategyLogic.calculate_indicators(df['close'].tolist())
        
        # Helper to run a single pass
        def simulate_strategy(strategy_name: str, direction: str = 'LONG') -> dict:
            capital = 1000.0
            position = 0.0
            entry_price = 0.0
            trades = []
            
            # Align dataframe with indicators
            # StrategyLogic returns Series with same index as list, so we can iterate
            
            # Start loop after indicators stabilize (First 50 candles)
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
                    if i == start_idx: signal = 1.0 # Buy at start
                    elif i == len(df)-1: signal = -1.0 # Sell at end
                
                # Execute
                if direction == 'LONG':
                    if signal > 0 and position == 0:
                        position = capital / price
                        capital = 0
                        trades.append({'side': 'buy', 'price': price, 'time': str(timestamp)})
                    elif signal < 0 and position > 0:
                        capital = position * price
                        position = 0
                        trades.append({'side': 'sell', 'price': price, 'time': str(timestamp)})
                elif direction == 'SHORT':
                    if signal < 0 and position == 0:
                        position = capital / price  # Using position as "borrowed units"
                        entry_price = price
                        capital = 0 
                        trades.append({'side': 'sell', 'price': price, 'time': str(timestamp)})
                    elif signal > 0 and position > 0:
                        profit = position * (entry_price - price)
                        capital = (position * entry_price) + profit
                        position = 0
                        trades.append({'side': 'buy', 'price': price, 'time': str(timestamp)})
            
            # Close position at end
            if position > 0:
                if direction == 'LONG':
                    capital = position * df['close'].iloc[-1]
                    trades.append({'side': 'sell', 'price': df['close'].iloc[-1], 'time': 'end'})
                elif direction == 'SHORT':
                    profit = position * (entry_price - df['close'].iloc[-1])
                    capital = (position * entry_price) + profit
                    trades.append({'side': 'buy', 'price': df['close'].iloc[-1], 'time': 'end'})
            
            # Calc metrics
            initial_capital = 1000.0
            pnl_pct = ((capital - initial_capital) / initial_capital) * 100
            
            # Calculate actual win rate from completed round-trip trades
            if direction == 'LONG':
                sell_trades = [t for t in trades if t['side'] == 'sell']
                buy_trades = [t for t in trades if t['side'] == 'buy']
                winning = 0
                total_roundtrips = min(len(buy_trades), len(sell_trades))
                for i in range(total_roundtrips):
                    if sell_trades[i]['price'] > buy_trades[i]['price']:
                        winning += 1
            elif direction == 'SHORT':
                sell_trades = [t for t in trades if t['side'] == 'sell']
                buy_trades = [t for t in trades if t['side'] == 'buy']
                winning = 0
                total_roundtrips = min(len(buy_trades), len(sell_trades))
                for i in range(total_roundtrips):
                    if buy_trades[i]['price'] < sell_trades[i]['price']:
                        winning += 1
                        
            win_rate = winning / total_roundtrips if total_roundtrips > 0 else 0.0
            
            return {
                'final_capital': round(capital, 2),
                'total_pnl_pct': round(pnl_pct, 2),
                'trades': total_roundtrips,
                'win_rate': round(win_rate, 2)
            }

        return {
            'agent': simulate_strategy('agent', 'LONG'),
            'agent_short': simulate_strategy('agent', 'SHORT'),
            'buy_hold': simulate_strategy('buy_hold', 'LONG'),
            'macd': simulate_strategy('macd', 'LONG'),
            'bollinger': simulate_strategy('bollinger', 'LONG')
        }
