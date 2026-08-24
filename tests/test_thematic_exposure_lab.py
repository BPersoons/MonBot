"""
Unit tests for utils/thematic_exposure_lab.py (EXP-008: Thematic Exposure Sleeve).

Runs entirely against mocked HL/yfinance/LLM/exchange_client data in a
temporary working directory — no live network calls, no real orders.
Safety-critical assertions (leverage=1, margin_mode=isolated on every order,
budget cap, min-notional/price-sanity/market-hours guards) are the priority
here since this module places real orders in production.

IMPORTANT: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are forcibly cleared for the
entire duration of this module's test run (setUpModule/tearDownModule below).
_notify_telegram() is a real method on ThematicExposureLab and several tests
exercise code paths that call it (e.g. a successful mocked _open_tranche) —
without this guard, running these tests against a dev machine that has real
Telegram credentials in its environment sends real messages describing fake
trades to the real chat. This bit us once already (2026-07-16): a test run
sent live "T1/T2 opened" notifications for a completely mocked exchange
client. Do not remove this guard; if a new test needs to assert Telegram
content, mock `_notify_telegram` directly instead of relying on real env vars.
"""

import json
import math
import os
import random
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from utils import thematic_exposure_lab as tel
from utils.thematic_exposure_lab import ThematicExposureLab

_ORIGINAL_ENV = {}
_BLOCKED_ENV_KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


def setUpModule():
    for key in _BLOCKED_ENV_KEYS:
        _ORIGINAL_ENV[key] = os.environ.pop(key, None)


def tearDownModule():
    for key, value in _ORIGINAL_ENV.items():
        if value is not None:
            os.environ[key] = value


def _flat_closes(n, price):
    return [price] * n


def _slow_crash_closes():
    """~29% drawdown from a clean early high, spread deterministically over
    ~230 sessions (MSFT-style slow bleed) — this is exactly what the v1 20d
    pullback window missed. Realistic gaussian noise is layered only onto the
    final ~20 sessions (the realized-vol lookback window), so normalization
    sees real-looking daily vol without the overall drawdown magnitude
    depending on random-walk luck over the full 252-day history."""
    closes = []
    price = 100.0
    daily_drift = -(0.29 / 230)
    for _ in range(230):
        price *= 1.0 + daily_drift
        closes.append(round(price, 4))
    rng = random.Random(42)
    for _ in range(22):
        price *= 1.0 + rng.gauss(daily_drift, 0.012)
        closes.append(round(max(price, 1.0), 4))
    return closes


def _fast_crash_closes():
    """Flat-ish for 230 sessions (same daily noise), then a sharp ~21% drop
    concentrated in the last 7 sessions (INTC-style)."""
    rng = random.Random(7)
    closes = []
    price = 100.0
    for _ in range(230):
        price *= 1.0 + rng.gauss(0, 0.012)
        closes.append(round(max(price, 1.0), 4))
    for _ in range(15):
        price *= 1.0 + rng.gauss(0, 0.012)
        closes.append(round(max(price, 1.0), 4))
    for _ in range(7):
        price *= 0.965  # sharp concentrated drop
        closes.append(round(price, 4))
    return closes


class ThematicExposureLabTestBase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        os.makedirs("config", exist_ok=True)
        # _classify_ticker valideert sinds 2026-07-17 via yfinance dat een
        # symbool historie heeft — in tests altijd "ja", geen netwerk. Tests
        # die het faal-pad testen overriden dit expliciet.
        patcher = patch.object(ThematicExposureLab, "_yf_has_history", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        # De prijs-sanity-guard (2026-07-21) haalt via _fetch_intraday_price een
        # VERSE koers bij yfinance op. Die is hier nooit gepatcht, waardoor vier
        # toetsen sinds de invoering rood stonden: ze zetten een mark van $100
        # voor XYZ-NVDA, de echte koers stond op $209, en de guard sloeg dus
        # elke order over — inclusief in
        # test_order_always_uses_leverage_1_isolated, die dit bestand zelf
        # veiligheidskritisch noemt. Een toets die op de dagkoers van NVDA
        # meebeweegt, toetst niets.
        #
        # 0.0 = "geen intraday-referentie", waarna _sanity_reference terugvalt
        # op state["price_cache"]; staat die er niet, dan slaat de guard over.
        # Toetsen die de guard ZELF willen zien vuren, patchen dit expliciet —
        # zie TestExecutionGuards.test_intraday_sanity_mismatch_skips_order.
        intraday = patch.object(ThematicExposureLab, "_fetch_intraday_price", return_value=0.0)
        intraday.start()
        self.addCleanup(intraday.stop)

        # De sector-circuit-breaker haalt via sector_drawdown_pct() de
        # XYZ100-dagcandles op — een echte ccxt-aanroep, goed voor ~13 seconden
        # per toets die _maybe_advance_tranches raakt. Hij wordt bovendien
        # ONVOORWAARDELIJK aangeroepen, ook als er niets te kopen valt.
        # 0.0 = "geen sector-daling", dus de breaker blokkeert niets.
        # TestSectorCircuitBreaker zet hem expliciet aan.
        cb = patch("core.equity_regime.sector_drawdown_pct", return_value=0.0)
        cb.start()
        self.addCleanup(cb.stop)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()

    @staticmethod
    def _seed_themes(tickers: dict, themes: dict = None):
        data = {
            "themes": themes or {"semiconductors": {"target_weight": 0.30}},
            "tickers": tickers,
            "pending": {},
        }
        with open(tel.THEMES_FILE, "w") as f:
            json.dump(data, f)
        return data


class TestCrashScoring(ThematicExposureLabTestBase):
    def setUp(self):
        super().setUp()
        self.lab = ThematicExposureLab(exchange_client=None)

    def test_slow_crash_scores_as_pullback(self):
        """A gradual -29% grind over ~250 sessions must still clear the
        pullback bar — this is exactly what the v1 20d-window design missed."""
        closes = _slow_crash_closes()
        current_price = closes[-1]
        score = self.lab._pullback_score(closes, current_price)
        self.assertGreater(score["pullback_z"], 0.0)
        self.assertGreater(score["drawdown_pct"], 20.0)

    def test_fast_crash_has_high_speed_component(self):
        """A sharp drop concentrated in the last 7 sessions must score a much
        higher speed_z than a slow grind of similar total magnitude."""
        fast_closes = _fast_crash_closes()
        fast_score = self.lab._pullback_score(fast_closes, fast_closes[-1])
        slow_closes = _slow_crash_closes()
        slow_score = self.lab._pullback_score(slow_closes, slow_closes[-1])
        self.assertGreater(fast_score["speed_z"], slow_score["speed_z"])

    def test_stabilization_false_at_5d_low(self):
        """Price sitting exactly at the 5-day low must NOT be flagged
        stabilized — 'buy the dip, not the free fall'."""
        closes = _flat_closes(240, 100.0) + [90, 80, 70, 60, 50]
        score = self.lab._pullback_score(closes, 50.0)  # current == 5d low
        self.assertFalse(score["stabilized"])

    def test_stabilization_true_after_bounce(self):
        closes = _flat_closes(240, 100.0) + [90, 80, 70, 60, 65]
        score = self.lab._pullback_score(closes, 65.0)  # bounced off the low
        self.assertTrue(score["stabilized"])

    def test_empty_history_returns_zero_score_not_exception(self):
        score = self.lab._pullback_score([], 100.0)
        self.assertEqual(score["pullback_z"], 0.0)
        self.assertFalse(score["stabilized"])

    def test_zero_volatility_does_not_divide_by_zero(self):
        closes = _flat_closes(260, 100.0)  # perfectly flat -> realized_vol == 0
        score = self.lab._pullback_score(closes, 100.0)
        self.assertEqual(score["pullback_z"], 0.0)


class TestThemeBreadth(ThematicExposureLabTestBase):
    def setUp(self):
        super().setUp()
        self.lab = ThematicExposureLab(exchange_client=None)

    def test_breadth_requires_multiple_members_hit(self):
        themes_cfg = {
            "themes": {"semiconductors": {}},
            "tickers": {
                "XYZ-A": {"real_symbol": "A", "themes": {"semiconductors": 0.5}, "status": "CONFIRMED"},
                "XYZ-B": {"real_symbol": "B", "themes": {"semiconductors": 0.5}, "status": "CONFIRMED"},
                "XYZ-C": {"real_symbol": "C", "themes": {"semiconductors": 0.5}, "status": "CONFIRMED"},
            },
        }
        # Only one of three members is deeply pulled back -> breadth should be low
        scores = {
            "XYZ-A": {"pullback_z": 3.0},
            "XYZ-B": {"pullback_z": 0.1},
            "XYZ-C": {"pullback_z": 0.1},
        }
        breadth = self.lab._theme_breadth(scores, themes_cfg)
        self.assertAlmostEqual(breadth["semiconductors"], 1 / 3)

    def test_breadth_zero_for_theme_with_no_confirmed_members(self):
        themes_cfg = {"themes": {"optical_networking": {}}, "tickers": {}}
        breadth = self.lab._theme_breadth({}, themes_cfg)
        self.assertEqual(breadth["optical_networking"], 0.0)

    def test_breadth_ignores_unscoreable_members(self):
        """CONFIRMED leden zonder score (geen yfinance-historie / te dun)
        horen niet in de noemer — anders drukt een onmeetbare naam als
        Samsung/Kioxia de breadth van precies het kern-thema structureel
        onder de drempel (bug 2026-07-17)."""
        themes_cfg = {
            "themes": {"memory_storage": {}},
            "tickers": {
                "XYZ-MU": {"real_symbol": "MU", "themes": {"memory_storage": 0.5}, "status": "CONFIRMED"},
                "XYZ-SNDK": {"real_symbol": "SNDK", "themes": {"memory_storage": 0.5}, "status": "CONFIRMED"},
                "XYZ-SMSN": {"real_symbol": "SMSN", "themes": {"memory_storage": 0.5}, "status": "CONFIRMED"},
                "XYZ-KIOXIA": {"real_symbol": "KIOXIA", "themes": {"memory_storage": 0.5}, "status": "CONFIRMED"},
            },
        }
        # SMSN/KIOXIA hebben geen score (geen prijshistorie) — noemer = 2
        scores = {"XYZ-MU": {"pullback_z": 3.0}, "XYZ-SNDK": {"pullback_z": 2.0}}
        breadth = self.lab._theme_breadth(scores, themes_cfg)
        self.assertAlmostEqual(breadth["memory_storage"], 1.0)


class TestPriceHistoryFetch(ThematicExposureLabTestBase):
    """_fetch_price_history: FX-conversie naar USD + negatieve cache.
    yfinance wordt volledig gemockt via sys.modules — geen netwerk."""

    def setUp(self):
        super().setUp()
        self.lab = ThematicExposureLab(exchange_client=None)

    @staticmethod
    def _fake_yf_frame(closes_by_symbol: dict):
        import pandas as pd
        n = max(len(v) for v in closes_by_symbol.values())
        idx = pd.date_range("2026-01-01", periods=n, freq="D")
        cols = {}
        for sym, closes in closes_by_symbol.items():
            padded = [float("nan")] * (n - len(closes)) + list(closes)
            cols[(sym, "Close")] = padded
        df = pd.DataFrame(cols, index=idx)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    def _run_fetch(self, symbol_specs, closes_by_symbol):
        import sys
        fake_yf = MagicMock()
        fake_yf.download.return_value = self._fake_yf_frame(closes_by_symbol)
        with patch.dict(sys.modules, {"yfinance": fake_yf}):
            result = self.lab._fetch_price_history(symbol_specs)
        return result, fake_yf

    def test_fx_symbol_converts_closes_to_usd(self):
        """9984.T-closes in JPY gedeeld door JPY=X → USD-closes, zodat
        drawdown-scoring en de prijs-sanity-guard tegen HL's USD-mark kloppen."""
        result, _ = self._run_fetch(
            {"9984.T": "JPY=X"},
            {"9984.T": [16000.0] * 30, "JPY=X": [160.0] * 30},
        )
        self.assertIn("9984.T", result)
        self.assertTrue(all(abs(c - 100.0) < 1e-9 for c in result["9984.T"]["closes"]))

    def test_unfetchable_symbol_lands_in_negative_cache(self):
        result, _ = self._run_fetch(
            {"NVDA": None, "SOFTBANK": None},
            {"NVDA": [100.0] * 30},  # SOFTBANK ontbreekt volledig
        )
        self.assertIn("NVDA", result)
        self.assertNotIn("SOFTBANK", result)
        state = self.lab._load_state()
        self.assertIn("SOFTBANK", state.get("price_cache_failed", {}))

    def test_negative_cache_prevents_refetch_loop(self):
        """Zonder negatieve cache bleef een onfetchbaar symbool eeuwig
        'missing' → volledige 1y-batch elke run opnieuw + dezelfde yfinance-
        ERRORs naar Telegram elke ~5 min (bug 2026-07-17)."""
        specs = {"NVDA": None, "SOFTBANK": None}
        self._run_fetch(specs, {"NVDA": [100.0] * 30})
        # tweede run: NVDA vers gecachet, SOFTBANK in negatieve cache → geen download
        import sys
        fake_yf = MagicMock()
        with patch.dict(sys.modules, {"yfinance": fake_yf}):
            result = self.lab._fetch_price_history(specs)
        fake_yf.download.assert_not_called()
        self.assertIn("NVDA", result)


class TestClassification(ThematicExposureLabTestBase):
    def setUp(self):
        super().setUp()
        self.lab = ThematicExposureLab(exchange_client=None)

    def test_high_confidence_llm_response_auto_confirms(self):
        """2026-07-16, Bart's verzoek: high-confidence voorstellen tellen
        direct mee (live T1-executie-eligible), geen menselijke review meer."""
        themes = self._seed_themes({})
        mock_llm = MagicMock()
        mock_llm.analyze_text.return_value = (
            '```json\n{"themes": {"semiconductors": 0.8}, "confidence": "high"}\n```'
        )
        with patch.object(self.lab, "_get_llm", return_value=mock_llm):
            result = self.lab._classify_ticker("XYZ-FOO", themes)
        entry = themes["tickers"]["XYZ-FOO"]
        self.assertEqual(entry["status"], "CONFIRMED")
        self.assertEqual(entry["themes"]["semiconductors"], 0.8)
        self.assertEqual(entry["real_symbol"], "FOO")
        self.assertEqual(result, ("XYZ-FOO", "CONFIRMED", {"semiconductors": 0.8}))

    def test_low_confidence_llm_response_stays_pending_review(self):
        """Even a real proposal stays human-reviewed when the LLM itself
        flags uncertainty — the auto-confirm safety net."""
        themes = self._seed_themes({})
        mock_llm = MagicMock()
        mock_llm.analyze_text.return_value = '{"themes": {"semiconductors": 0.4}, "confidence": "low"}'
        with patch.object(self.lab, "_get_llm", return_value=mock_llm):
            self.lab._classify_ticker("XYZ-BAR", themes)
        self.assertEqual(themes["tickers"]["XYZ-BAR"]["status"], "PENDING_REVIEW")

    def test_missing_confidence_field_stays_pending_review(self):
        """A malformed/omitted confidence field must default to the safe
        (human-reviewed) path, never to auto-confirm."""
        themes = self._seed_themes({})
        mock_llm = MagicMock()
        mock_llm.analyze_text.return_value = '{"themes": {"semiconductors": 0.4}}'
        with patch.object(self.lab, "_get_llm", return_value=mock_llm):
            self.lab._classify_ticker("XYZ-BAZ2", themes)
        self.assertEqual(themes["tickers"]["XYZ-BAZ2"]["status"], "PENDING_REVIEW")

    def test_garbage_llm_response_sets_pending_manual(self):
        themes = self._seed_themes({})
        mock_llm = MagicMock()
        mock_llm.analyze_text.return_value = "not json at all"
        with patch.object(self.lab, "_get_llm", return_value=mock_llm):
            self.lab._classify_ticker("XYZ-BAR", themes)
        self.assertEqual(themes["tickers"]["XYZ-BAR"]["status"], "PENDING_MANUAL")

    def test_llm_unavailable_sets_pending_manual(self):
        themes = self._seed_themes({})
        with patch.object(self.lab, "_get_llm", return_value=None):
            self.lab._classify_ticker("XYZ-BAZ", themes)
        self.assertEqual(themes["tickers"]["XYZ-BAZ"]["status"], "PENDING_MANUAL")

    def test_no_yfinance_history_blocks_auto_confirm(self):
        """HL-codes als SOFTBANK/KIOXIA zijn geen Yahoo-symbolen: high
        confidence of niet, zonder prijshistorie is de naam onscoorbaar en
        moet hij PENDING_MANUAL worden — mét bewaard thema-voorstel zodat
        alleen de symbol-mapping handwerk is (bug 2026-07-17)."""
        themes = self._seed_themes({})
        mock_llm = MagicMock()
        mock_llm.analyze_text.return_value = '{"themes": {"semiconductors": 0.9}, "confidence": "high"}'
        with patch.object(self.lab, "_get_llm", return_value=mock_llm), \
             patch.object(ThematicExposureLab, "_yf_has_history", return_value=False):
            result = self.lab._classify_ticker("XYZ-SOFTBANK", themes)
        entry = themes["tickers"]["XYZ-SOFTBANK"]
        self.assertEqual(entry["status"], "PENDING_MANUAL")
        self.assertEqual(entry["themes"], {"semiconductors": 0.9})  # voorstel bewaard
        self.assertEqual(result, ("XYZ-SOFTBANK", "PENDING_MANUAL", {}))

    def test_scan_new_tickers_filters_non_equity_before_llm(self):
        """FX/index/commodity tickers must never reach the LLM or generate a
        notification — bug 2026-07-16 spammed Telegram with one message per
        ticker for the whole ~100-ticker XYZ universe, most of it non-equity."""
        self._seed_themes({})
        snapshot = {
            "XYZ-DXY": {"mark_px": 100.0}, "XYZ-KR200": {"mark_px": 1000.0},
            "XYZ-GOLD": {"mark_px": 4000.0},
            "XYZ-NVDA": {"mark_px": 200.0, "day_volume_usd": 50_000_000.0},
        }
        self.lab._save_state({"universe_seeded": True})
        mock_llm = MagicMock()
        mock_llm.analyze_text.return_value = '{"themes": {"semiconductors": 0.5}, "confidence": "high"}'
        with patch.object(self.lab, "_xyz_snapshot", return_value=snapshot), \
             patch.object(self.lab, "_get_llm", return_value=mock_llm):
            self.lab._scan_new_tickers()
        data = self.lab._load_themes()
        self.assertEqual(data["tickers"]["XYZ-DXY"]["status"], "IGNORED")
        self.assertEqual(data["tickers"]["XYZ-KR200"]["status"], "IGNORED")
        self.assertEqual(data["tickers"]["XYZ-GOLD"]["status"], "IGNORED")
        self.assertEqual(data["tickers"]["XYZ-NVDA"]["status"], "CONFIRMED")  # high confidence -> auto
        # Only NVDA should have triggered an LLM call — 3 non-equity tickers skipped it
        self.assertEqual(mock_llm.analyze_text.call_count, 1)

    def test_thin_ticker_auto_ignored_before_llm(self):
        """2026-07-16, Bart's verzoek: alleen belangrijke/liquide bedrijven,
        geen brede dekking van elke dunne HL-listing — dat is precies de
        ruis die de crash-detectie moet uitfilteren."""
        self._seed_themes({})
        snapshot = {
            "XYZ-THIN": {"mark_px": 5.0, "day_volume_usd": 100_000.0},  # ver onder de drempel
            "XYZ-NVDA": {"mark_px": 200.0, "day_volume_usd": 50_000_000.0},
        }
        self.lab._save_state({"universe_seeded": True})
        mock_llm = MagicMock()
        mock_llm.analyze_text.return_value = '{"themes": {"semiconductors": 0.5}, "confidence": "high"}'
        with patch.object(self.lab, "_xyz_snapshot", return_value=snapshot), \
             patch.object(self.lab, "_get_llm", return_value=mock_llm):
            self.lab._scan_new_tickers()
        data = self.lab._load_themes()
        self.assertEqual(data["tickers"]["XYZ-THIN"]["status"], "IGNORED")
        self.assertEqual(data["tickers"]["XYZ-NVDA"]["status"], "CONFIRMED")
        self.assertEqual(mock_llm.analyze_text.call_count, 1)  # only NVDA reached the LLM

    def test_scan_sends_one_batched_notification_not_per_ticker(self):
        self._seed_themes({})
        snapshot = {"XYZ-AAA": {"mark_px": 10.0, "day_volume_usd": 50_000_000.0},
                    "XYZ-BBB": {"mark_px": 20.0, "day_volume_usd": 50_000_000.0}}
        self.lab._save_state({"universe_seeded": True})
        mock_llm = MagicMock()
        mock_llm.analyze_text.return_value = '{"themes": {"semiconductors": 0.5}, "confidence": "high"}'
        with patch.object(self.lab, "_xyz_snapshot", return_value=snapshot), \
             patch.object(self.lab, "_get_llm", return_value=mock_llm), \
             patch.object(self.lab, "_notify_telegram") as mock_notify:
            self.lab._scan_new_tickers()
        mock_notify.assert_called_once()
        _, kwargs = mock_notify.call_args
        self.assertTrue(kwargs.get("plain"))  # must never risk Markdown-parsing underscores in theme IDs

    def test_batch_notification_separates_auto_confirmed_from_reviewable(self):
        self._seed_themes({})
        snapshot = {"XYZ-HIGH": {"mark_px": 10.0, "day_volume_usd": 50_000_000.0},
                    "XYZ-LOW": {"mark_px": 20.0, "day_volume_usd": 50_000_000.0}}
        self.lab._save_state({"universe_seeded": True})
        mock_llm = MagicMock()
        mock_llm.analyze_text.side_effect = [
            '{"themes": {"semiconductors": 0.9}, "confidence": "high"}',
            '{"themes": {"semiconductors": 0.3}, "confidence": "low"}',
        ]
        with patch.object(self.lab, "_xyz_snapshot", return_value=snapshot), \
             patch.object(self.lab, "_get_llm", return_value=mock_llm), \
             patch.object(self.lab, "_notify_telegram") as mock_notify:
            self.lab._scan_new_tickers()
        text = mock_notify.call_args[0][0]
        self.assertIn("Auto-CONFIRMED", text)
        self.assertIn("XYZ-HIGH", text)
        self.assertIn("low confidence, review gewenst", text)
        self.assertIn("XYZ-LOW", text)

    def test_pending_manual_only_batch_shows_count_not_per_ticker_spam(self):
        self._seed_themes({})
        snapshot = {"XYZ-WEIRD": {"mark_px": 5.0, "day_volume_usd": 50_000_000.0}}
        self.lab._save_state({"universe_seeded": True})
        with patch.object(self.lab, "_xyz_snapshot", return_value=snapshot), \
             patch.object(self.lab, "_get_llm", return_value=None), \
             patch.object(self.lab, "_notify_telegram") as mock_notify:
            self.lab._scan_new_tickers()
        mock_notify.assert_called_once()
        text = mock_notify.call_args[0][0]
        self.assertIn("1 zonder voorstel", text)

    def test_first_scan_seeds_without_classifying(self):
        """First-ever universe scan must not treat the whole existing
        universe as 'new' (same guard as shadow_xyz_lab's listing detector)."""
        self._seed_themes({})
        with patch.object(self.lab, "_xyz_snapshot", return_value={"XYZ-NVDA": {"mark_px": 200}}):
            with patch.object(self.lab, "_classify_ticker") as mock_classify:
                self.lab._scan_new_tickers()
                mock_classify.assert_not_called()
        state = self.lab._load_state()
        self.assertTrue(state.get("universe_seeded"))


class TestExecutionGuards(ThematicExposureLabTestBase):
    def setUp(self):
        super().setUp()
        self.exchange = MagicMock()
        self.exchange.get_market_price.return_value = 100.0
        self.exchange.get_min_notional.return_value = 10.0
        self.exchange.get_amount_precision.return_value = 0.0001
        self.exchange.create_order.return_value = {"id": "mock-order-1"}
        self.lab = ThematicExposureLab(exchange_client=self.exchange)
        self.themes_cfg = self._seed_themes({
            "XYZ-NVDA": {"real_symbol": "NVDA", "themes": {"semiconductors": 0.4}, "status": "CONFIRMED"},
        })
        self.positions = self.lab._load_positions()  # fresh default budget

    def _report(self):
        return {"scores": {"XYZ-NVDA": {"mark_px": 100.0, "theme_breadth": 0.5}}}

    def test_order_always_uses_leverage_1_isolated(self):
        with patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        self.exchange.create_order.assert_called_once()
        _, kwargs = self.exchange.create_order.call_args
        self.assertEqual(kwargs.get("leverage"), 1)
        self.assertEqual(kwargs.get("margin_mode"), "isolated")

    def test_market_closed_skips_order(self):
        with patch("agents.xyz_technical_analyst._market_is_open", return_value=False):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        self.exchange.create_order.assert_not_called()

    def test_price_sanity_mismatch_skips_order(self):
        state = self.lab._load_state()
        state["price_cache"] = {"NVDA": {"closes": [50.0]}}  # >2% away from mark_px=100.0
        self.lab._save_state(state)
        with patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        self.exchange.create_order.assert_not_called()

    def test_intraday_sanity_mismatch_skips_order(self):
        """De INTRADAY-tak van de guard, met een strakke band.

        De testbasis zet _fetch_intraday_price standaard op 0.0 zodat toetsen
        niet meebewegen met de echte koers van NVDA. Daardoor liep deze tak
        nergens meer langs — precies het gat dat hem in juli onopgemerkt liet.
        Hier dus expliciet aangezet.
        """
        with patch.object(ThematicExposureLab, "_fetch_intraday_price", return_value=209.0), \
                patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        self.exchange.create_order.assert_not_called()

    def test_intraday_binnen_de_band_laat_de_order_door(self):
        """Tegenproef: zonder deze zou een guard die ALTIJD blokkeert ook slagen."""
        with patch.object(ThematicExposureLab, "_fetch_intraday_price", return_value=100.5), \
                patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        self.exchange.create_order.assert_called_once()

    def test_below_min_notional_skips_order(self):
        self.exchange.get_min_notional.return_value = 10_000.0  # tranche is always under this
        with patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        self.exchange.create_order.assert_not_called()

    def test_insufficient_cash_skips_order(self):
        self.positions["cash_usd"] = 0.01
        with patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        self.exchange.create_order.assert_not_called()

    def test_budget_cap_decrements_cash_correctly(self):
        starting_cash = self.positions["cash_usd"]
        with patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        expected_tranche = (starting_cash / tel.MAX_CONCURRENT_NAMES) * tel.TRANCHE_PCTS[1]
        self.assertAlmostEqual(self.positions["cash_usd"], starting_cash - expected_tranche, places=2)
        self.assertIn("XYZ-NVDA", self.positions["positions"])
        self.assertEqual(self.positions["positions"]["XYZ-NVDA"]["status"], "OPEN")

    def test_second_tranche_updates_weighted_avg_entry(self):
        """Bijkopen moet de entryprijs MENGEN, niet overschrijven.

        Draait met een tijdelijk verlengd plan: sinds 2026-08-24 telt
        TRANCHE_PCTS één stap, zodat `_open_tranche(…, 2, …)` op een KeyError
        zou stuiten. De menglogica blijft gelden zodra het budget groter wordt
        en er weer meerdere stappen komen — dus blijft hij getoetst.
        """
        with patch.dict(tel.TRANCHE_PCTS, {1: 0.60, 2: 0.40}, clear=True):
            with patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
                self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
            self.exchange.get_market_price.return_value = 80.0  # price dropped further
            with patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
                self.lab._open_tranche("XYZ-NVDA", 2, self.themes_cfg, self.positions, self._report())
        pos = self.positions["positions"]["XYZ-NVDA"]
        self.assertEqual(pos["tranche_stage"], 2)
        self.assertTrue(80.0 < pos["avg_entry_price"] < 100.0)  # blended, not overwritten

    def test_order_failure_does_not_record_position(self):
        self.exchange.create_order.return_value = None
        with patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._open_tranche("XYZ-NVDA", 1, self.themes_cfg, self.positions, self._report())
        self.assertNotIn("XYZ-NVDA", self.positions.get("positions", {}))


class TestTrancheTriggers(unittest.TestCase):
    def test_t2_logica_blijft_intact_voor_een_langer_plan(self):
        """T2 zit sinds 2026-08-24 niet meer in het plan, de regel wel.

        Het plan is teruggebracht tot een enkele stap: T2 vuurde op -10% t.o.v.
        entry en was dus geconditioneerd op ongelijk hebben, terwijl
        `t2_t4_enabled` bovendien nooit aan heeft gestaan. De regel zelf blijft
        staan voor een groter budget, dus hij blijft getoetst — met een
        tijdelijk verlengd plan, net als T3/T4 hieronder.
        """
        with patch.dict(tel.TRANCHE_PCTS, {2: 0.0}):
            pos = {"avg_entry_price": 100.0}
            drop_met_breadth = {"mark_px": 88.0, "theme_breadth": 0.5}   # -12%
            drop_zonder_breadth = {"mark_px": 80.0, "theme_breadth": 0.0}
            self.assertTrue(ThematicExposureLab._tranche_trigger(2, drop_met_breadth, pos))
            self.assertFalse(ThematicExposureLab._tranche_trigger(2, drop_zonder_breadth, pos))

    def test_t2_vuurt_niet_in_het_huidige_plan(self):
        """Het plan telt één stap; T2 mag dus door niets worden aangezet."""
        self.assertNotIn(2, tel.TRANCHE_PCTS,
                         "plan bevat T2 weer — pas deze toets dan aan")
        self.assertFalse(ThematicExposureLab._tranche_trigger(
            2, {"mark_px": 88.0, "theme_breadth": 0.5}, {"avg_entry_price": 100.0}))

    def test_stappen_buiten_het_plan_vuren_nooit(self):
        """Sinds 2026-08-12 telt het plan twee stappen, niet vier.

        Deze twee toetsen eisten tot 2026-08-24 nog het OUDE gedrag (T3 vuurt op
        `recovering`, T4 op een hernieuwde val) en stonden dus rood sinds de dag
        dat het plan werd ingekort. De code kreeg toen een guard bovenaan
        `_tranche_trigger` — stap niet in TRANCHE_PCTS is False — maar de toetsen
        volgden niet mee. Dit is nu het contract dat bewaakt wordt.
        """
        for stage in (3, 4):
            self.assertNotIn(stage, tel.TRANCHE_PCTS,
                             "plan bevat T%d weer — pas deze toets dan aan" % stage)
        # ...en dan mag geen enkele score hem alsnog laten vuren.
        self.assertFalse(ThematicExposureLab._tranche_trigger(3, {"recovering": True}, {}))
        self.assertFalse(ThematicExposureLab._tranche_trigger(4, {"pullback_z": 3.0}, {}))

    def test_t3_t4_logica_blijft_intact_voor_een_langer_plan(self):
        """De T3/T4-regels zijn bewust blijven staan voor een groter budget.

        Zonder deze toets is dat dode code die niemand meer controleert — en die
        bij het terugzetten van een vier-stappenplan stil verkeerd kan blijken.
        """
        with patch.dict(tel.TRANCHE_PCTS, {3: 0.0, 4: 0.0}):
            self.assertTrue(ThematicExposureLab._tranche_trigger(3, {"recovering": True}, {}))
            self.assertFalse(ThematicExposureLab._tranche_trigger(3, {"recovering": False}, {}))
            self.assertTrue(ThematicExposureLab._tranche_trigger(4, {"pullback_z": 3.0}, {}))
            self.assertFalse(ThematicExposureLab._tranche_trigger(4, {"pullback_z": 0.5}, {}))


class TestBudgetIsolation(ThematicExposureLabTestBase):
    """Positions written by this module must never leak into the swarm's
    learning loop — verified at the StrategyManager guard (execution_agent's
    guards are simple one-line additions verified by direct code inspection,
    same pattern as the existing 'harvest' guard)."""

    def test_strategy_manager_holds_thematic_exposure_positions(self):
        from agents.strategy_manager import StrategyManager
        with patch("agents.strategy_manager.StrategyManager.__init__", return_value=None):
            sm = StrategyManager()
        result = sm.evaluate_position({"thematic_exposure": True, "entry_price": 100.0, "action": "BUY"}, 90.0)
        self.assertEqual(result["action"], "HOLD")


class TestT2T4DryRunGate(ThematicExposureLabTestBase):
    def setUp(self):
        super().setUp()
        self.exchange = MagicMock()
        self.exchange.get_market_price.return_value = 80.0
        self.lab = ThematicExposureLab(exchange_client=self.exchange)

    def test_t2_t4_stays_dry_run_when_flag_off(self):
        positions = {
            "budget_usd": 1250.0, "cash_usd": 1000.0,
            "positions": {"XYZ-NVDA": {"status": "OPEN", "tranche_stage": 1, "avg_entry_price": 100.0}},
        }
        self.lab._save_positions(positions)
        self.lab._save_state({"t2_t4_enabled": False})
        report = {"scores": {"XYZ-NVDA": {"mark_px": 88.0, "theme_breadth": 0.5}}, "qualifying": []}
        self.lab._maybe_advance_tranches(report)
        self.exchange.create_order.assert_not_called()

    def test_t2_t4_executes_when_flag_on(self):
        self._seed_themes({
            "XYZ-NVDA": {"real_symbol": "NVDA", "themes": {"semiconductors": 0.4}, "status": "CONFIRMED"},
        })
        positions = {
            "budget_usd": 1250.0, "cash_usd": 1000.0,
            "positions": {"XYZ-NVDA": {"status": "OPEN", "tranche_stage": 1, "avg_entry_price": 100.0,
                                        "quantity": 1.0, "cost_basis_usd": 100.0}},
        }
        self.lab._save_positions(positions)
        self.lab._save_state({"t2_t4_enabled": True})
        self.exchange.get_min_notional.return_value = 10.0
        self.exchange.get_amount_precision.return_value = 0.0001
        self.exchange.create_order.return_value = {"id": "mock-order-2"}
        report = {"scores": {"XYZ-NVDA": {"mark_px": 88.0, "theme_breadth": 0.5}}, "qualifying": []}
        # Verlengd plan: het huidige telt één stap (zie TRANCHE_PCTS), dus zonder
        # dit zou T2 nergens meer op afketsen en toetst de vlag niets meer.
        # MAX_TRANCHE_STAGE wordt bij import afgeleid en moet dus mee.
        with patch.dict(tel.TRANCHE_PCTS, {1: 0.60, 2: 0.40}, clear=True), \
                patch.object(tel, "MAX_TRANCHE_STAGE", 2), \
                patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
            self.lab._maybe_advance_tranches(report)
        self.exchange.create_order.assert_called_once()



class TestWinstbescherming(ThematicExposureLabTestBase):
    """De winstladder en de trailing-stop (2026-08-24).

    Achtergrond: de winstladder (25% afromen bij +30/+60/+100%) heeft in het
    hele bestaan van de sleeve nooit gevuurd, omdat 25% van een positie van
    $16-28 onder HL's $10-minimum blijft. Daardoor bleef ook onopgemerkt dat
    een geslaagde trim de piekwaarde NIET meeschaalde — waarna de trailing-stop
    de eerstvolgende cyclus gegarandeerd de hele winnaar liquideerde.
    """

    def setUp(self):
        super().setUp()
        self.exchange = MagicMock()
        self.exchange.get_amount_precision.return_value = 0.0001
        self.exchange.create_order.return_value = {"id": "mock-exit-1"}
        self.lab = ThematicExposureLab(exchange_client=self.exchange)

    def _seed_positie(self, quantity, entry, **extra):
        pos = {
            "themes": {"semiconductors": 0.4},
            "tranche_stage": 1,
            "status": "OPEN",
            "quantity": quantity,
            "avg_entry_price": entry,
            "cost_basis_usd": quantity * entry,
            "opened_at": tel._now_iso(),
        }
        pos.update(extra)
        data = self.lab._load_positions()
        data["positions"] = {"XYZ-NVDA": pos}
        self.lab._save_positions(data)
        return pos

    def _positie(self):
        return self.lab._load_positions()["positions"]["XYZ-NVDA"]

    # ── de ladder zelf ───────────────────────────────────────────────────
    def test_trail_fraction_per_band(self):
        self.assertEqual(tel._trail_fraction(0.0), tel.SLEEVE_TRAIL_BASE)
        self.assertEqual(tel._trail_fraction(29.9), tel.SLEEVE_TRAIL_BASE)
        self.assertEqual(tel._trail_fraction(30.0), 0.85)
        self.assertEqual(tel._trail_fraction(59.9), 0.85)
        self.assertEqual(tel._trail_fraction(60.0), 0.88)
        self.assertEqual(tel._trail_fraction(100.0), 0.92)
        self.assertEqual(tel._trail_fraction(250.0), 0.92)

    def test_ladder_wordt_strenger_niet_losser(self):
        """Elke hogere piek moet een STRAKKERE stop geven, nooit een lossere."""
        vorige = tel.SLEEVE_TRAIL_BASE
        for piek in (0, 30, 60, 100, 200):
            huidig = tel._trail_fraction(piek)
            self.assertGreaterEqual(huidig, vorige,
                                    "stop werd losser bij piek +%s%%" % piek)
            vorige = huidig

    # ── de regressie: trim mag de winnaar niet liquideren ────────────────
    def test_trim_liquideert_de_rest_niet(self):
        # 0,5 stuks a $100 entry, mark $130 = +30%. Waarde $65, dus 25% = $16,25
        # en dat haalt HL's $10-minimum wel — anders zou de trim niet vuren en
        # test deze zaak niets.
        self._seed_positie(0.5, 100.0)
        self.exchange.get_market_price.return_value = 130.0

        self.lab._manage_exits()                      # cyclus 1: trimt 25%
        na_trim = self._positie()
        self.assertEqual(na_trim["status"], "OPEN")
        self.assertTrue(na_trim.get("profit_tranche_1_done"))
        self.assertAlmostEqual(na_trim["quantity"], 0.375, places=6)
        # de piek moet met dezelfde 25% zijn meegeschaald
        self.assertAlmostEqual(na_trim["peak_value_usd"], 48.75, places=4)

        self.exchange.create_order.reset_mock()
        self.lab._manage_exits()                      # cyclus 2: prijs onveranderd
        na_tweede = self._positie()
        self.assertEqual(
            na_tweede["status"], "OPEN",
            "de trailing-stop liquideerde de winnaar direct na de winst-tranche")
        self.exchange.create_order.assert_not_called()

    def test_trailing_stop_vuurt_wel_bij_echte_terugval(self):
        """De strakkere stop moet ook echt sluiten — anders is hij decoratie."""
        self._seed_positie(0.5, 100.0)
        self.exchange.get_market_price.return_value = 140.0   # piek +40%
        self.lab._manage_exits()
        self.assertEqual(self._positie()["status"], "OPEN")

        # -14% vanaf de piek: binnen de oude 20%-regel, buiten de nieuwe 15%.
        self.exchange.get_market_price.return_value = 118.0
        self.lab._manage_exits()
        self.assertEqual(self._positie()["status"], "CLOSED")

    def test_onder_30_procent_blijft_de_oude_20_procent_regel(self):
        self._seed_positie(0.5, 100.0)
        self.exchange.get_market_price.return_value = 120.0   # piek +20%
        self.lab._manage_exits()
        # -14% vanaf de piek mag bij een kleine winnaar nog NIET sluiten
        self.exchange.get_market_price.return_value = 103.5
        self.lab._manage_exits()
        self.assertEqual(self._positie()["status"], "OPEN")

    # ── het $10-minimum: tranche bewaren, niet verbranden ────────────────
    def test_close_or_trim_bewaart_een_te_kleine_deelexit(self):
        """`_close_or_trim` mag een sub-minimum deelexit nooit als gedaan boeken.

        LET OP — deze toets richt zich bewust op `_close_or_trim` zelf en niet
        meer op `_manage_exits`. Tot eerder vandaag bewaarde de hele keten de
        sport bij een te kleine positie; sinds de regel "te kleine winnaar gaat
        helemaal dicht" bereikt een WINST-sport dit pad niet meer (zie
        TestWinstbescherming.test_te_kleine_winnaar_gaat_helemaal_dicht).

        De guard blijft er wel toe doen als laatste vangnet: de hogere regel
        rekent met `current_value_usd`, terwijl hier pas op de precisie wordt
        afgerond. Een order die daardoor alsnog onder de vloer uitkomt moet
        stilvallen zonder de sport te verbranden — de fout van 2026-08-20.
        """
        pos = self._seed_positie(0.2, 50.0)
        positions = self.lab._load_positions()
        pos = positions["positions"]["XYZ-NVDA"]
        pos["current_value_usd"] = 0.2 * 65.0

        gelukt = self.lab._close_or_trim(positions, "XYZ-NVDA", pos, 65.0,
                                         tel.SLEEVE_PROFIT_TRIM_FRACTION, "winst-tranche +30%")

        self.assertFalse(gelukt, "een niet-uitvoerbare deelexit meldde succes")
        self.exchange.create_order.assert_not_called()
        self.assertAlmostEqual(pos["quantity"], 0.2, places=6)

    def test_volledige_sluiting_wordt_altijd_geprobeerd(self):
        """Een VOLLEDIGE sluiting kent geen ondergrens — daar valt niets te bewaren."""
        positions = self.lab._load_positions()
        positions["positions"] = {"XYZ-NVDA": dict(self._seed_positie(0.05, 50.0))}
        pos = positions["positions"]["XYZ-NVDA"]
        pos["current_value_usd"] = 0.05 * 65.0        # $3,25 -- ruim onder de vloer

        gelukt = self.lab._close_or_trim(positions, "XYZ-NVDA", pos, 65.0, 1.0, "downside-stop")

        self.assertTrue(gelukt)
        self.exchange.create_order.assert_called_once()



    # ── te kleine winnaar: helemaal dicht ────────────────────────────────
    def test_te_kleine_winnaar_gaat_helemaal_dicht(self):
        """Een positie die zijn sport raakt maar niet af te romen is, sluit heel.

        0,2 stuks a $50 = $10 kostprijs, mark $65 = +30%. Waarde $13, en 25%
        daarvan is $3,25 -- onder HL's $10. Voorheen bleef zo'n positie eeuwig
        de sport overslaan; nu komt het kapitaal terug op volle grootte.
        """
        self._seed_positie(0.2, 50.0)
        self.exchange.get_market_price.return_value = 65.0

        self.lab._manage_exits()
        pos = self._positie()
        self.assertEqual(pos["status"], "CLOSED")
        self.assertAlmostEqual(pos["quantity"], 0.0, places=6)
        self.exchange.create_order.assert_called_once()
        _, kwargs = self.exchange.create_order.call_args
        self.assertEqual(kwargs.get("leverage"), 1)
        self.assertEqual(kwargs.get("margin_mode"), "isolated")

    def test_grote_genoeg_winnaar_roomt_af_en_blijft_open(self):
        """Tegenproef -- anders zou een regel die ALLES sluit ook slagen.

        0,5 stuks a $100 = $50 kostprijs, mark $130 = +30%. Waarde $65, 25%
        daarvan is $16,25 en dat haalt de vloer. Dit is de nieuwe standaard-
        grootte ($42,50/naam), dus dit pad hoort het normale te zijn.
        """
        self._seed_positie(0.5, 100.0)
        self.exchange.get_market_price.return_value = 130.0

        self.lab._manage_exits()
        pos = self._positie()
        self.assertEqual(pos["status"], "OPEN")
        self.assertAlmostEqual(pos["quantity"], 0.375, places=6)
        self.assertTrue(pos.get("profit_tranche_1_done"))

    def test_verliezer_wordt_niet_door_deze_regel_geraakt(self):
        """De regel geldt alleen op winst-sporten, niet op een kleine verliezer."""
        self._seed_positie(0.2, 50.0)
        self.exchange.get_market_price.return_value = 45.0   # -10%, geen sport
        self.lab._manage_exits()
        self.assertEqual(self._positie()["status"], "OPEN")
        self.exchange.create_order.assert_not_called()

class TestSectorCircuitBreaker(ThematicExposureLabTestBase):
    """De sector-circuit-breaker: pauzeer NIEUWE dip-buys bij een structurele
    sectordaling, maar blijf bestaande posities beheren.

    Deze guard had tot 2026-08-24 GEEN enkele toets, terwijl hij bepaalt of er
    überhaupt gekocht wordt. Hij viel op doordat hij per toets ~13 seconden aan
    live koersuitvraag kostte; toen bleek dat niemand hem ooit had vastgelegd.
    """

    def setUp(self):
        super().setUp()
        self.exchange = MagicMock()
        self.exchange.get_market_price.return_value = 100.0
        self.exchange.get_min_notional.return_value = 10.0
        self.exchange.get_amount_precision.return_value = 0.0001
        self.exchange.create_order.return_value = {"id": "mock-cb-1"}
        self.lab = ThematicExposureLab(exchange_client=self.exchange)
        self.themes_cfg = self._seed_themes({
            "XYZ-NVDA": {"real_symbol": "NVDA", "themes": {"semiconductors": 0.4},
                         "status": "CONFIRMED"},
        })
        self.lab._save_positions({"budget_usd": 1250.0, "cash_usd": 1000.0, "positions": {}})

    def _report(self):
        return {"scores": {"XYZ-NVDA": {"mark_px": 100.0, "theme_breadth": 0.5}},
                "qualifying": ["XYZ-NVDA"]}

    def _advance(self, drawdown_pct):
        cb = patch("core.equity_regime.sector_drawdown_pct", return_value=drawdown_pct)
        markt = patch("agents.xyz_technical_analyst._market_is_open", return_value=True)
        with cb, markt:
            self.lab._maybe_advance_tranches(self._report())

    def test_structurele_daling_pauzeert_nieuwe_koop(self):
        self._advance(tel.SLEEVE_CIRCUIT_BREAKER_DD_PCT + 5.0)
        self.exchange.create_order.assert_not_called()

    def test_rustige_markt_laat_koop_door(self):
        """Tegenproef — zonder deze zou een breaker die ALTIJD blokkeert ook slagen."""
        self._advance(0.0)
        self.exchange.create_order.assert_called_once()

    def test_precies_op_de_drempel_blokkeert(self):
        """>= en niet >: op de drempel zelf hoort hij te pauzeren."""
        self._advance(tel.SLEEVE_CIRCUIT_BREAKER_DD_PCT)
        self.exchange.create_order.assert_not_called()

    def test_net_onder_de_drempel_laat_door(self):
        self._advance(tel.SLEEVE_CIRCUIT_BREAKER_DD_PCT - 0.1)
        self.exchange.create_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
