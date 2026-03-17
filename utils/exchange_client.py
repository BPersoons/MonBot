import ccxt
import os
import logging
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
    def __init__(self, testnet=True):
        self.logger = logging.getLogger("HyperliquidExchange")
        self.testnet = testnet
        self.exchange_id = 'hyperliquid'
        
        # 1. View-Only Client (Public Data)
        try:
            self.public_client = ccxt.hyperliquid({
                'enableRateLimit': True,
                'options': {'defaultType': 'swap', 'fetchMarkets': {'types': ['swap']}}
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

        # 2. Signing Client (Execution) - Use GCP Secrets
        self.signing_client = None
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
                    'options': {'defaultType': 'swap', 'fetchMarkets': {'types': ['swap']}}
                })
                if testnet:
                    self.signing_client.set_sandbox_mode(True)
                auth_mode = f"API wallet {self.wallet_address} -> vault {wallet_for_ccxt}" if vault_address else self.wallet_address
                self.logger.info(f"Hyperliquid Signing Client Initialized: {auth_mode}")
            except Exception as e:
                self.logger.error(f"Failed to initialize Signing Client: {e}")
        else:
            self.logger.warning("HL_PRIVATE_KEY or HL_WALLET_ADDRESS missing. Execution will fail.")

    def _normalize_symbol(self, ticker):
        """
        Normalize a ticker symbol for Hyperliquid CCXT.
        Hyperliquid perps use the format BASE/USDC:USDC (e.g. SOL/USDC:USDC).
        Returns None if the symbol cannot be found in the loaded markets.
        """
        if not self.markets:
            return ticker
        # Replace USDT with USDC first
        if "/USDT" in ticker:
            ticker = ticker.replace("/USDT", "/USDC")
        # Direct match
        if ticker in self.markets:
            return ticker
        # Try the perpetual format: BASE/USDC:USDC
        perp = ticker + ":USDC" if not ticker.endswith(":USDC") else ticker
        if perp in self.markets:
            return perp
        # Last resort: just the base asset (e.g. "SOL")
        base = ticker.split("/")[0]
        if base in self.markets:
            return base
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

    def create_order(self, ticker, action, quantity, price=None, order_type='market'):
        """
        Executes an On-Chain Order using the Signing Client.
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
            params = {}
            
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

    def get_balance(self):
        """
        Fetches total account balance (USDC).
        """
        client = self.signing_client if self.signing_client else self.public_client
        if not client:
            return 0.0
            
        try:
            # Hyperliquid requires the user/vault address in params
            user_addr = getattr(self, 'vault_address', None) or self.wallet_address
            balance = client.fetch_balance(params={'user': user_addr})

            # Hyperliquid uses USDC as collateral.
            usdc_balance = balance.get('USDC', {}).get('total', 0.0)
            if usdc_balance == 0.0 and 'total' in balance:
                usdc_balance = balance['total'].get('USDC', 0.0)

            return usdc_balance
        except Exception as e:
            self.logger.error(f"Error fetching balance: {e}")
            return 0.0

    def get_free_margin(self):
        """Returns free (available) USDC margin as reported by Hyperliquid."""
        client = self.signing_client if self.signing_client else self.public_client
        if not client:
            return 0.0
        try:
            user_addr = getattr(self, 'vault_address', None) or self.wallet_address
            balance = client.fetch_balance(params={'user': user_addr})
            free = balance.get('USDC', {}).get('free', 0.0)
            if not free:
                free = balance.get('free', {}).get('USDC', 0.0)
            return float(free or 0.0)
        except Exception as e:
            self.logger.warning(f"Error fetching free margin: {e}")
            return 0.0

# Alias for compatibility if code imports PaperExchange
# But we should prefer renaming usages.
PaperExchange = HyperliquidExchange
