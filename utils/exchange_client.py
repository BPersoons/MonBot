import ccxt
import os
import logging
import threading
from dotenv import load_dotenv
import time
import json
from eth_account import Account


load_dotenv()
# Fallback to .env.adk if standard .env didn't provide keys
if not os.getenv("HL_WALLET_ADDRESS"):
    load_dotenv(".env.adk")

def _get_hl_credentials():
    """Get Hyperliquid credentials from GCP Secret Manager or environment.

    Returns (api_wallet, private_key, vault_address).
    vault_address is the main wallet that authorized the API wallet — required by CCXT
    when using an agent/API wallet. If None, api_wallet is used as walletAddress (legacy).
    """
    try:
        from utils.gcp_secrets import get_hyperliquid_wallet, get_hyperliquid_private_key, get_hyperliquid_vault_address
        wallet = get_hyperliquid_wallet()
        private_key = get_hyperliquid_private_key()
        vault = get_hyperliquid_vault_address()
        if wallet and private_key:
            return wallet, private_key, vault
    except ImportError:
        pass

    # Fallback to environment
    return os.getenv("HL_WALLET_ADDRESS"), os.getenv("HL_PRIVATE_KEY"), os.getenv("HL_VAULT_ADDRESS")

class HyperliquidExchange:
    """
    Connects to Hyperliquid Testnet via CCXT.
    Uses Private Key for signing orders (On-Chain).
    Separates 'Signing Wallet' from 'View-Only' logic.
    """
    def __init__(self, testnet=True, wallet_address=None, private_key=None, vault_address=None):
        """
        wallet_address/private_key/vault_address: pass explicitly to run this
        instance against a DIFFERENT Hyperliquid account than the main swarm
        wallet (e.g. a sleeve with its own segregated wallet) — bypasses
        _get_hl_credentials()'s default HL_WALLET_ADDRESS/HL_PRIVATE_KEY/
        HL_VAULT_ADDRESS lookup entirely. Leave all three None for the
        original single-account behavior.
        """
        self.logger = logging.getLogger("HyperliquidExchange")
        self.testnet = testnet
        self.exchange_id = 'hyperliquid'
        self._explicit_credentials = wallet_address and private_key
        
        # 1. View-Only Client (Public Data)
        try:
            self.public_client = ccxt.hyperliquid({
                'enableRateLimit': True,
                'options': {'defaultType': 'swap'}
            })
            if testnet:
                self.public_client.set_sandbox_mode(True)
            
            # Load markets to populate symbols
            self.markets = self.public_client.load_markets()
            self.logger.info(f"Hyperliquid Public Client Initialized. Available Symbols: {len(self.markets)}")
        except Exception as e:
            self.logger.error(f"Failed to initialize Public Client: {e}")
            self.public_client = None
            self.markets = {}
        self._last_markets_reload = 0.0
        # SwarmMonitor runs its checks (balance/positions/etc.) in a separate daemon
        # thread against this SAME HyperliquidExchange instance, concurrently with the
        # main loop — same "shared ccxt client" thread-safety concern that made
        # agents/technical_analyst.py's _get_shared_exchange() add a _FETCH_LOCK.
        # Guards reload-on-miss so two threads can't race a concurrent
        # load_markets(reload=True) into a corrupted/partial self.markets.
        self._markets_reload_lock = threading.Lock()

        # 2. Signing Client (Execution) - Use GCP Secrets, unless explicit
        # credentials were passed in for a segregated-wallet instance.
        self.signing_client = None
        if self._explicit_credentials:
            self.wallet_address = wallet_address
        else:
            self.wallet_address, private_key, vault_address = _get_hl_credentials()

        if private_key and self.wallet_address:
            try:
                # When using an API/agent wallet, CCXT requires:
                #   walletAddress = main vault wallet (the one that authorized the API wallet)
                #   apiKey        = API wallet address
                #   privateKey    = API wallet private key
                wallet_for_ccxt = vault_address if vault_address else self.wallet_address
                self.vault_address = wallet_for_ccxt  # main wallet — used for balance queries
                self.signing_client = ccxt.hyperliquid({
                    'apiKey': self.wallet_address,
                    'secret': private_key,
                    'walletAddress': wallet_for_ccxt,
                    'privateKey': private_key,
                    'enableRateLimit': True,
                    'options': {'defaultType': 'swap'}
                })
                if testnet:
                    self.signing_client.set_sandbox_mode(True)
                auth_mode = f"API wallet {self.wallet_address} -> vault {wallet_for_ccxt}" if vault_address else self.wallet_address
                self.logger.info(f"Hyperliquid Signing Client Initialized: {auth_mode}")
            except Exception as e:
                self.logger.error(f"Failed to initialize Signing Client: {e}")
        else:
            self.logger.warning("HL_PRIVATE_KEY or HL_WALLET_ADDRESS missing. Execution will fail.")

    _MARKETS_RELOAD_COOLDOWN_S = 300  # rate-limit reload-on-miss so a batch of misses in one cycle can't storm the API

    def _lookup_symbol(self, ticker):
        """Pure dict lookup against self.markets — no I/O. Returns the resolved
        symbol or None."""
        # Replace USDT with USDC first
        if "/USDT" in ticker:
            ticker = ticker.replace("/USDT", "/USDC")
        # Always try perpetual format first (swap > spot)
        perp = ticker + ":USDC" if not ticker.endswith(":USDC") else ticker
        if perp in self.markets:
            return perp
        # Direct match (already includes :USDC, or XYZ-assets without spot)
        if ticker in self.markets:
            return ticker
        # Last resort: just the base asset (e.g. "SOL")
        base = ticker.split("/")[0]
        if base in self.markets:
            return base
        return None

    def _maybe_reload_markets(self) -> bool:
        """Best-effort, rate-limited reload triggered by a symbol lookup miss.
        2026-07-17: a subset of XYZ equity tickers (e.g. XYZ-NVDA/MSFT/BABA/CRWV)
        intermittently resolved as "not listed" on this long-lived instance's
        self.markets, silently blocking the Thematic Exposure sleeve's entries/
        exits with no error anywhere — even immediately after a call to
        load_markets(reload=True) that reported the full 761-symbol count. A
        brand-new, unshared HyperliquidExchange resolved the same tickers
        reliably every time in isolated testing. Root cause NOT confirmed:
        SwarmMonitor's watchdog thread calls methods on this SAME instance's
        public_client concurrently with the main loop (same class of concern
        _get_shared_exchange's _FETCH_LOCK exists for in technical_analyst.py),
        so the lock below at least serializes our own reloads — but testing
        after adding it still showed the same misses, so an unsynchronized race
        in this code is not the (or not the only) explanation. Keep the lock as
        cheap insurance; if this recurs, compare raw ccxt fetch_markets() output
        between a failing and a fresh instance to find the actual divergence
        before adding more retry logic. Cooldown avoids a reload-per-miss storm
        regardless — reload is a full markets fetch (~11.6s)."""
        now = time.time()
        if now - self._last_markets_reload < self._MARKETS_RELOAD_COOLDOWN_S:
            return False
        with self._markets_reload_lock:
            # Re-check inside the lock: another thread may have just reloaded
            # while we were waiting to acquire it.
            now = time.time()
            if now - self._last_markets_reload < self._MARKETS_RELOAD_COOLDOWN_S:
                return False
            self._last_markets_reload = now
            try:
                self.markets = self.public_client.load_markets(reload=True)
                self.logger.info(f"HyperliquidExchange: reloaded markets after a lookup miss ({len(self.markets)} symbols)")
                return True
            except Exception as e:
                self.logger.warning(f"HyperliquidExchange: markets reload failed: {e}")
                return False

    def _normalize_symbol(self, ticker):
        """
        Normalize a ticker symbol for Hyperliquid CCXT.
        Hyperliquid perps use the format BASE/USDC:USDC (e.g. SOL/USDC:USDC).
        Always prefers perpetual (swap) over spot when both exist.
        Returns None if the symbol cannot be found in the loaded markets (after
        one rate-limited reload attempt — see _maybe_reload_markets).
        """
        if not self.markets:
            return ticker
        found = self._lookup_symbol(ticker)
        if found:
            return found
        if self._maybe_reload_markets():
            found = self._lookup_symbol(ticker)
            if found:
                return found
        # Symbol does not exist on this exchange
        return None

    def get_market_price(self, ticker):
        """
        Fetches the mid-price for a ticker. Returns 0.0 if the ticker is
        not listed on Hyperliquid or has no active quotes.
        """
        if not self.public_client:
            return 0.0

        symbol = self._normalize_symbol(ticker)
        if symbol is None:
            self.logger.warning(f"Ticker {ticker} not listed on Hyperliquid — skipping price fetch.")
            return 0.0

        try:
            ticker_data = self.public_client.fetch_ticker(symbol)
            # last can be None on testnet markets with no recent trades
            price = ticker_data.get('last') or ticker_data.get('close') or \
                    ticker_data.get('bid') or ticker_data.get('ask')
            if price is None:
                self.logger.warning(f"No price data for {symbol} (all fields None — illiquid market).")
                return 0.0
            return float(price)
        except Exception as e:
            self.logger.error(f"Error fetching price for {symbol}: {e}")
            return 0.0

    def get_l1_orderbook(self, ticker):
        """
        Fetches L1 Order Book (Best Bid/Ask).
        """
        if not self.public_client:
            return None
        symbol = self._normalize_symbol(ticker)
        if symbol is None:
            return None
        try:
            orderbook = self.public_client.fetch_order_book(symbol, limit=1)
            return {
                "bid": orderbook['bids'][0][0] if orderbook['bids'] else 0,
                "ask": orderbook['asks'][0][0] if orderbook['asks'] else 0
            }
        except Exception as e:
            self.logger.error(f"Error fetching L1 OB for {ticker}: {e}")
            return None

    def get_trade_costs(self, ticker, since_ms):
        """
        Sum the REAL trading costs for a symbol since a given timestamp (ms),
        straight from the HL ledgers: taker/maker fees over all fills (entry,
        partials, close) and net funding payments.

        Returns (fees_usd, funding_received_usd):
          fees_usd             — total fees paid, always >= 0
          funding_received_usd — net funding, positive = received, negative = paid
        Either value is None when that ledger could not be fetched — callers
        must treat None as "unknown", never as 0.
        """
        client = self.signing_client or self.public_client
        if not client or not since_ms:
            return None, None
        symbol = self._normalize_symbol(ticker)
        if symbol is None:
            return None, None

        fees = None
        try:
            fills = client.fetch_my_trades(symbol, since=int(since_ms), limit=200)
            fees = 0.0
            for f in fills:
                cost = (f.get('fee') or {}).get('cost')
                if cost:
                    fees += abs(float(cost))
        except Exception as e:
            self.logger.warning(f"get_trade_costs: fills fetch failed for {symbol}: {e}")

        funding = None
        try:
            events = client.fetch_funding_history(symbol, since=int(since_ms), limit=500)
            funding = 0.0
            for ev in events:
                amt = ev.get('amount')
                if amt is not None:
                    # HL userFunding: positive = received, negative = paid.
                    funding += float(amt)
        except Exception as e:
            self.logger.warning(f"get_trade_costs: funding fetch failed for {symbol}: {e}")

        return fees, funding

    def create_order(self, ticker, action, quantity, price=None, order_type='market',
                      leverage=None, margin_mode=None, reduce_only=False):
        """
        Executes an On-Chain Order using the Signing Client.

        leverage/margin_mode: optional per-order overrides. When omitted (None),
        behavior is unchanged from before these params existed — DEFAULT_LEVERAGE
        env var, cross-then-isolated fallback. Pass explicit values to pin a
        specific mode for callers that must not inherit the swarm-wide default
        (e.g. a buy-and-hold sleeve that must never be leveraged).

        reduce_only: MUST be True for every closing/partial-exit order. Without it
        a "close" order on a position the exchange doesn't actually have is just a
        normal market order — it OPENS the opposite position. That is exactly how
        two orphan shorts were created (2026-07-24 $2.107 notional, 2026-07-28
        $128) while the swarm booked fictional profit on them. reduceOnly makes it
        an exchange-level guarantee instead of a check-then-act race.
        """
        if not self.signing_client:
            self.logger.error("No Signing Client available.")
            return None

        symbol = self._normalize_symbol(ticker)
        if symbol is None:
            self.logger.error(f"Cannot place order: {ticker} is not listed on Hyperliquid.")
            return None
        try:
            ticker = symbol
            side = action.lower()
            params = {"reduceOnly": True} if reduce_only else {}

            # Set leverage — 3x default for more positions with small bankroll
            # TP/SL/PnL percentages are on notional, so they stay correct
            target_leverage = int(leverage) if leverage is not None else int(os.getenv("DEFAULT_LEVERAGE", "3"))
            if margin_mode is not None:
                try:
                    self.signing_client.set_leverage(target_leverage, ticker, params={'marginMode': margin_mode})
                except Exception as lev_err:
                    self.logger.warning(f"set_leverage({target_leverage}, marginMode={margin_mode}) failed for {ticker}: {lev_err}")
            else:
                try:
                    self.signing_client.set_leverage(target_leverage, ticker, params={'marginMode': 'cross'})
                except Exception:
                    try:
                        self.signing_client.set_leverage(target_leverage, ticker, params={'marginMode': 'isolated'})
                    except Exception as lev_err:
                        self.logger.warning(f"set_leverage({target_leverage}) failed for {ticker}: {lev_err}")

            self.logger.info(f"Signing {side} order for {quantity} {ticker}...")

            if order_type == 'market':
                # CCXT Hyperliquid requires price for market orders (slippage calculation)
                if price is None:
                    price = self.get_market_price(ticker)
                order = self.signing_client.create_order(ticker, 'market', side, quantity, price, params=params)
            else:
                order = self.signing_client.create_order(ticker, 'limit', side, quantity, price, params=params)

            self.logger.info(f"On-Chain Order Sent: {order['id']}")
            return order
            
        except Exception as e:
            err_str = str(e)
            if "does not exist" in err_str:
                self.logger.warning(
                    f"Wallet {self.wallet_address} is not registered on Hyperliquid "
                    f"(no deposits found). Trading suspended until wallet is funded. Raw: {e}"
                )
                self.signing_client = None  # Prevent further attempts
            elif "Insufficient margin" in err_str:
                self.logger.warning(f"Insufficient margin to place order for {ticker} — account fully allocated, skipping.")
            else:
                self.logger.error(f"On-Chain Order Failed: {e}")
            return None

    def fetch_order_status(self, order_id, ticker):
        """
        Checks status of an order via Public API (using ID).
        """
        # Usually check via signing client to see own orders, or public if we have the ID.
        client = self.signing_client if self.signing_client else self.public_client
        if not client:
            return None
            
        symbol = self._normalize_symbol(ticker)
        if symbol is None:
            return None
        try:
            order = client.fetch_order(order_id, symbol)
            return order
        except Exception as e:
            self.logger.error(f"Error fetching order {order_id}: {e}")
            return None

    def get_funding_rate(self, ticker):
        """
        Fetches current funding rate.
        """
        try:
            symbol = self._normalize_symbol(ticker)
            if symbol is None:
                return 0.0
            funding = self.public_client.fetch_funding_rate(symbol)
            return funding.get('fundingRate', 0.0)
        except Exception as e:
            return 0.0

    def get_amount_precision(self, ticker):
        """Returns the amount precision step for a market (e.g. 0.01 for SOL, 1.0 for ASTER)."""
        try:
            symbol = self._normalize_symbol(ticker)
            return self.markets.get(symbol, {}).get('precision', {}).get('amount', 0.0) or 0.0
        except Exception:
            return 0.0

    def get_min_notional(self, ticker):
        """Returns the minimum order cost in USD (e.g. $10 on Hyperliquid)."""
        try:
            symbol = self._normalize_symbol(ticker)
            return self.markets.get(symbol, {}).get('limits', {}).get('cost', {}).get('min', 10.0) or 10.0
        except Exception:
            return 10.0

    # ---------- SPOT (buy-and-hold conviction sleeve: UBTC/UETH via HL spot) ----------
    def _spot_symbol(self, base):
        """Map a base coin to its HL spot ccxt symbol, e.g. 'BTC' -> 'BTC/USDC'.
        NB: spot has NO ':USDC' suffix (that's the perp). Returns None if unlisted."""
        sym = f"{base.upper()}/USDC"
        return sym if sym in self.markets else None

    def get_spot_price(self, base):
        """Last spot price for a base coin (e.g. 'BTC'). 0.0 on failure."""
        sym = self._spot_symbol(base)
        if not sym:
            return 0.0
        try:
            t = self.public_client.fetch_ticker(sym)
            return float(t.get("last") or 0.0)
        except Exception as e:
            self.logger.debug(f"get_spot_price({base}) failed: {e}")
            return 0.0

    def get_spot_holdings(self, user_addr=None):
        """All spot token balances for the account, as {coin: total_units}.
        Reads spotClearinghouseState directly (CCXT ignores the 'user' param and
        would query the API wallet, not the vault)."""
        user_addr = user_addr or getattr(self, "vault_address", None) or self.wallet_address
        out = {}
        if not user_addr:
            return out
        try:
            import urllib.request, json as _json
            payload = _json.dumps({"type": "spotClearinghouseState", "user": user_addr}).encode()
            req = urllib.request.Request(
                "https://api.hyperliquid.xyz/info", data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as r:
                data = _json.loads(r.read())
            for entry in data.get("balances", []):
                coin = entry.get("coin")
                if coin:
                    out[coin] = float(entry.get("total", 0.0) or 0.0)
        except Exception as e:
            self.logger.error(f"get_spot_holdings failed: {e}")
        return out

    def get_spot_meta(self, base):
        """(min_cost_usd, amount_precision) for a spot market. Defaults ($10, 0.0)."""
        sym = self._spot_symbol(base)
        if not sym:
            return 10.0, 0.0
        m = self.markets.get(sym, {})
        min_cost = (m.get("limits", {}).get("cost", {}) or {}).get("min", 10.0) or 10.0
        prec = (m.get("precision", {}) or {}).get("amount", 0.0) or 0.0
        return float(min_cost), float(prec)

    def create_spot_order(self, base, action, quantity, price=None):
        """Place a SPOT market order on HL for a base coin (e.g. 'BTC' -> 'BTC/USDC').

        Spot has NO leverage — this deliberately does NOT touch set_leverage (unlike
        create_order() for perps). Used by the buy-and-hold conviction sleeve. Buys
        spend spot USDC; sells return spot USDC. Returns the order dict or None.
        """
        if not self.signing_client:
            self.logger.error("No Signing Client available (spot order).")
            return None
        sym = self._spot_symbol(base)
        if not sym:
            self.logger.error(f"Spot market for {base} not listed on Hyperliquid.")
            return None
        try:
            side = action.lower()
            if price is None:
                price = self.get_spot_price(base)
            if not price:
                self.logger.error(f"create_spot_order: no price for {sym}.")
                return None
            order = self.signing_client.create_order(sym, 'market', side, quantity, price, params={})
            oid = order.get("id") if isinstance(order, dict) else None
            self.logger.info(f"Spot order sent: {oid} ({side} {quantity} {sym} @ ~{price})")
            return order
        except Exception as e:
            err = str(e)
            if "does not exist" in err:
                self.logger.warning(f"Spot order failed — wallet not registered: {e}")
            elif "Insufficient" in err:
                self.logger.warning(f"Spot order failed — insufficient spot USDC for {sym}.")
            else:
                self.logger.error(f"Spot order failed for {sym}: {e}")
            return None

    def _fetch_spot_balance(self, user_addr):
        """Fetch spot USDC total and hold via direct HL API."""
        import urllib.request, json as _json
        payload = _json.dumps({"type": "spotClearinghouseState", "user": user_addr}).encode()
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info", data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            spot_data = _json.loads(r.read())
        for entry in spot_data.get("balances", []):
            if entry.get("coin") == "USDC":
                return float(entry.get("total", 0.0)), float(entry.get("hold", 0.0))
        return 0.0, 0.0

    def _fetch_perp_state(self, user_addr):
        """Fetch perp clearinghouse state via direct HL API (not CCXT).

        CCXT's fetch_balance ignores the 'user' param and always queries the
        API wallet address. When vault_address differs from wallet_address
        (agent wallet setup), CCXT returns the API wallet's balance ($999)
        instead of the vault's actual perp state. Bug discovered April 2026:
        reported $1494 equity when real equity was $495.
        """
        import urllib.request, json as _json
        payload = _json.dumps({"type": "clearinghouseState", "user": user_addr}).encode()
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info", data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            perp_data = _json.loads(r.read())
        ms = perp_data.get("marginSummary", {})
        unrealized_pnl = 0.0
        for pos in perp_data.get("assetPositions", []):
            p = pos.get("position", {})
            unrealized_pnl += float(p.get("unrealizedPnl", 0))
        return {
            "accountValue": float(ms.get("accountValue", 0)),
            "totalRawUsd": float(ms.get("totalRawUsd", 0)),
            "totalMarginUsed": float(ms.get("totalMarginUsed", 0)),
            "totalNtlPos": float(ms.get("totalNtlPos", 0)),
            "unrealizedPnl": unrealized_pnl,
        }

    def get_balance(self):
        """
        Fetches total portfolio equity (USDC) for Hyperliquid Unified Account.

        In Unified mode, all USDC lives on the spot clearinghouse. The spot
        balance is NEVER reduced when perps are opened — HL just earmarks
        (holds) collateral from the spot total. The perp clearinghouse's
        accountValue includes the borrowed margin from spot, so adding
        spot + accountValue double-counts the pledged portion.

        Correct formula (verified April 2026 against HL UI):
            total_equity = spot_usdc + perp_unrealized_pnl

        spot_usdc already contains all deposited USDC (including amounts
        pledged to perps). Only the unrealized PnL from open perp positions
        is additional equity not reflected in spot.

        Uses direct HL API instead of CCXT because CCXT's fetch_balance
        ignores the 'user' param and queries the API wallet, not the vault.
        """
        user_addr = getattr(self, 'vault_address', None) or self.wallet_address
        if not user_addr:
            return 0.0

        spot_usdc = 0.0
        try:
            spot_usdc, _ = self._fetch_spot_balance(user_addr)
        except Exception as e:
            self.logger.debug(f"Could not fetch spot balance: {e}")

        perp_unrealized = 0.0
        try:
            perp_state = self._fetch_perp_state(user_addr)
            perp_unrealized = perp_state["unrealizedPnl"]
        except Exception as e:
            self.logger.error(f"Error fetching perp state: {e}")

        total = spot_usdc + perp_unrealized
        self.logger.info(f"Balance: spot=${spot_usdc:.2f} + perp_unreal=${perp_unrealized:.2f} = ${total:.2f}")
        return total

    def get_unrealized_pnl(self):
        """Return total unrealized PnL from all open perp positions.
        Uses direct HL API to query the vault address (not CCXT).
        """
        user_addr = getattr(self, 'vault_address', None) or self.wallet_address
        if not user_addr:
            return 0.0
        try:
            perp_state = self._fetch_perp_state(user_addr)
            return perp_state["unrealizedPnl"]
        except Exception as e:
            self.logger.debug(f"Could not fetch unrealized PnL: {e}")
            return 0.0

    def get_free_margin(self):
        """
        Returns actual free USDC margin available for NEW orders.

        In Unified mode, free margin = spot_total - spot_hold.
        spot_hold covers both XYZ position margin AND perp collateral pledges.
        Verified against HL UI "Available Balance" (April 2026).

        Uses direct HL API (not CCXT) — see _fetch_perp_state docstring.
        """
        user_addr = getattr(self, 'vault_address', None) or self.wallet_address
        if not user_addr:
            return 0.0

        try:
            spot_total, spot_hold = self._fetch_spot_balance(user_addr)
            free = max(0.0, spot_total - spot_hold)
            return free
        except Exception as e:
            self.logger.warning(f"Error fetching free margin: {e}")
            return 0.0

    def fetch_all_positions(self):
        """
        Fetch positions from ALL Hyperliquid clearinghouses (standard perps + XYZ perps).

        Standard fetch_positions() only returns the main perp clearinghouse.
        XYZ-* assets (RWA/equities/commodities) live on a separate clearinghouse
        and must be queried by passing their symbols explicitly.

        Returns a list of CCXT position dicts (same format as fetch_positions).
        Sets self._xyz_fetch_ok to indicate whether XYZ clearinghouse was reachable.
        """
        client = self.signing_client
        if not client:
            return []

        user_addr = getattr(self, 'vault_address', None) or self.wallet_address

        all_positions = []
        self._xyz_fetch_ok = False

        # 1. Standard perps (BTC, ETH, SOL, etc.)
        try:
            std = client.fetch_positions(params={'user': user_addr})
            all_positions.extend(std)
        except Exception as e:
            self.logger.warning(f"fetch_all_positions: standard perps failed: {e}")

        # 2. XYZ perps — must be queried by symbol list
        xyz_symbols = [
            sym for sym in self.markets
            if sym.startswith("XYZ-") and self.markets[sym].get('type') == 'swap'
        ]
        if xyz_symbols:
            try:
                xyz = client.fetch_positions(xyz_symbols, params={'user': user_addr})
                # Only add positions not already in std (deduplicate by symbol)
                std_symbols = {p.get('symbol') for p in all_positions}
                for p in xyz:
                    if p.get('symbol') not in std_symbols:
                        all_positions.append(p)
                self._xyz_fetch_ok = True
            except Exception as e:
                self.logger.warning(f"fetch_all_positions: XYZ perps failed: {e}")
        else:
            self._xyz_fetch_ok = True  # no XYZ symbols to fetch

        return all_positions

# Alias for compatibility if code imports PaperExchange
# But we should prefer renaming usages.
PaperExchange = HyperliquidExchange
