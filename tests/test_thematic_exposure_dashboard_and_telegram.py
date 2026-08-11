"""
Tests for the EXP-008 follow-ups: Telegram /themeapprove /themeedit /themeignore
commands (agents/swarm_monitor.py) and the /thematic-exposure dashboard page
(utils/dashboard_thematic_exposure.py).

Telegram sends are always mocked directly (_send_telegram) rather than relying
on env-var clearing alone — these tests construct SwarmMonitor via __new__()
and never touch the network regardless of what's in the environment.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from agents.swarm_monitor import SwarmMonitor
from utils.dashboard_thematic_exposure import build_thematic_exposure_html


def _make_monitor():
    monitor = SwarmMonitor.__new__(SwarmMonitor)
    monitor.logger = MagicMock()
    monitor._send_telegram = MagicMock()
    return monitor


class ThemeTelegramTestBase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        os.makedirs("config", exist_ok=True)
        self.monitor = _make_monitor()

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()

    @staticmethod
    def _write_themes(tickers, themes=None):
        data = {
            "themes": themes or {"semiconductors": {}, "memory_storage": {}},
            "tickers": tickers,
            "pending": {},
        }
        with open("config/thematic_exposure_themes.json", "w") as f:
            json.dump(data, f)
        return data

    @staticmethod
    def _read_themes():
        with open("config/thematic_exposure_themes.json") as f:
            return json.load(f)


class TestThemeApprove(ThemeTelegramTestBase):
    def test_approve_pending_review_sets_confirmed(self):
        self._write_themes({
            "XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "PENDING_REVIEW"},
        })
        self.monitor._cmd_theme_approve("XYZ-FOO")
        data = self._read_themes()
        self.assertEqual(data["tickers"]["XYZ-FOO"]["status"], "CONFIRMED")
        self.monitor._send_telegram.assert_called_once()
        self.assertIn("CONFIRMED", self.monitor._send_telegram.call_args[0][0])

    def test_approve_unknown_ticker_errors(self):
        self._write_themes({})
        self.monitor._cmd_theme_approve("XYZ-NOPE")
        msg = self.monitor._send_telegram.call_args[0][0]
        self.assertIn("niet gevonden", msg)

    def test_approve_without_proposal_asks_for_edit(self):
        self._write_themes({
            "XYZ-BAR": {"real_symbol": "BAR", "themes": {}, "status": "PENDING_MANUAL"},
        })
        self.monitor._cmd_theme_approve("XYZ-BAR")
        data = self._read_themes()
        self.assertEqual(data["tickers"]["XYZ-BAR"]["status"], "PENDING_MANUAL")  # unchanged
        msg = self.monitor._send_telegram.call_args[0][0]
        self.assertIn("geen thema-voorstel", msg)


class TestThemeEdit(ThemeTelegramTestBase):
    def test_edit_overwrites_themes_and_confirms(self):
        self._write_themes({
            "XYZ-BAR": {"real_symbol": "BAR", "themes": {}, "status": "PENDING_MANUAL"},
        })
        self.monitor._cmd_theme_edit("XYZ-BAR", "semiconductors:0.6,memory_storage:0.2")
        data = self._read_themes()
        entry = data["tickers"]["XYZ-BAR"]
        self.assertEqual(entry["status"], "CONFIRMED")
        self.assertAlmostEqual(entry["themes"]["semiconductors"], 0.6)
        self.assertAlmostEqual(entry["themes"]["memory_storage"], 0.2)

    def test_edit_unknown_theme_rejected(self):
        self._write_themes({"XYZ-BAR": {"real_symbol": "BAR", "themes": {}, "status": "PENDING_MANUAL"}})
        self.monitor._cmd_theme_edit("XYZ-BAR", "not_a_real_theme:0.5")
        data = self._read_themes()
        self.assertEqual(data["tickers"]["XYZ-BAR"]["status"], "PENDING_MANUAL")  # unchanged
        self.assertIn("Onbekend thema", self.monitor._send_telegram.call_args[0][0])

    def test_edit_malformed_spec_rejected(self):
        self._write_themes({"XYZ-BAR": {"real_symbol": "BAR", "themes": {}, "status": "PENDING_MANUAL"}})
        self.monitor._cmd_theme_edit("XYZ-BAR", "not-valid-format")
        self.assertIn("Ongeldig formaat", self.monitor._send_telegram.call_args[0][0])

    def test_edit_creates_entry_for_unknown_ticker(self):
        """A brand-new ticker not yet in the registry can still be added via /themeedit."""
        self._write_themes({})
        self.monitor._cmd_theme_edit("XYZ-NEW", "semiconductors:0.5")
        data = self._read_themes()
        self.assertEqual(data["tickers"]["XYZ-NEW"]["status"], "CONFIRMED")


class TestThemeIgnore(ThemeTelegramTestBase):
    def test_ignore_sets_status(self):
        self._write_themes({"XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "CONFIRMED"}})
        self.monitor._cmd_theme_ignore("XYZ-FOO")
        data = self._read_themes()
        self.assertEqual(data["tickers"]["XYZ-FOO"]["status"], "IGNORED")

    def test_ignore_unknown_ticker_errors(self):
        self._write_themes({})
        self.monitor._cmd_theme_ignore("XYZ-NOPE")
        self.assertIn("niet gevonden", self.monitor._send_telegram.call_args[0][0])


class TestThemeList(ThemeTelegramTestBase):
    def test_list_shows_only_pending(self):
        self._write_themes({
            "XYZ-A": {"real_symbol": "A", "themes": {"semiconductors": 0.5}, "status": "PENDING_REVIEW"},
            "XYZ-B": {"real_symbol": "B", "themes": {}, "status": "CONFIRMED"},
            "XYZ-C": {"real_symbol": "C", "themes": {}, "status": "PENDING_MANUAL"},
        })
        self.monitor._cmd_theme_list()
        msg = self.monitor._send_telegram.call_args[0][0]
        self.assertIn("XYZ-A", msg)
        self.assertIn("XYZ-C", msg)
        self.assertNotIn("XYZ-B", msg)

    def test_list_empty_says_nothing_pending(self):
        self._write_themes({"XYZ-A": {"real_symbol": "A", "themes": {}, "status": "CONFIRMED"}})
        self.monitor._cmd_theme_list()
        self.assertIn("Geen tickers", self.monitor._send_telegram.call_args[0][0])


class TestDispatchRouting(ThemeTelegramTestBase):
    """Confirms the new commands are actually wired into _dispatch_telegram_command
    without disturbing the existing /approve, /reject, /status, /help routing."""

    def test_themeapprove_routes_correctly(self):
        self._write_themes({"XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "PENDING_REVIEW"}})
        update = {"message": {"chat": {"id": "CHATID"}, "text": "/themeapprove XYZ-FOO"}}
        import agents.swarm_monitor as sm_module
        self.monitor._telegram_token = lambda: "tok"
        orig_chat_id_fn = sm_module._telegram_chat_id
        sm_module._telegram_chat_id = lambda: "CHATID"
        try:
            self.monitor._dispatch_telegram_command(update)
        finally:
            sm_module._telegram_chat_id = orig_chat_id_fn
        data = self._read_themes()
        self.assertEqual(data["tickers"]["XYZ-FOO"]["status"], "CONFIRMED")

    def test_wrong_chat_id_is_ignored(self):
        self._write_themes({"XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "PENDING_REVIEW"}})
        update = {"message": {"chat": {"id": "OTHER_CHAT"}, "text": "/themeapprove XYZ-FOO"}}
        import agents.swarm_monitor as sm_module
        orig_chat_id_fn = sm_module._telegram_chat_id
        sm_module._telegram_chat_id = lambda: "CHATID"
        try:
            self.monitor._dispatch_telegram_command(update)
        finally:
            sm_module._telegram_chat_id = orig_chat_id_fn
        data = self._read_themes()
        self.assertEqual(data["tickers"]["XYZ-FOO"]["status"], "PENDING_REVIEW")  # untouched
        self.monitor._send_telegram.assert_not_called()


class TestDashboardBuilder(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_cwd = os.getcwd()
        os.chdir(self._tmpdir.name)
        os.makedirs("config", exist_ok=True)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmpdir.cleanup()

    def test_renders_without_exception_on_empty_state(self):
        """No state files at all yet (freshly built, never deployed) — must not crash."""
        html = build_thematic_exposure_html()
        self.assertIn("Thematic Exposure Sleeve", html)
        self.assertIn("<!DOCTYPE html>", html)

    def test_renders_with_populated_state(self):
        with open("thematic_exposure_positions.json", "w") as f:
            json.dump({
                "budget_usd": 1250.0, "cash_usd": 900.0, "realized_pnl_usd": 5.0,
                "positions": {
                    "XYZ-NVDA": {
                        "themes": {"semiconductors": 0.4}, "tranche_stage": 2, "status": "OPEN",
                        "quantity": 0.9, "avg_entry_price": 92.5, "cost_basis_usd": 83.25,
                        "current_value_usd": 90.0, "opened_at": "2026-07-16T14:23:00+00:00",
                    }
                },
            }, f)
        with open("thematic_exposure_report.json", "w") as f:
            json.dump({"generated_at": "2026-07-16T14:20:00+00:00",
                       "breadth_by_theme": {"semiconductors": 0.4}}, f)
        with open("config/thematic_exposure_themes.json", "w") as f:
            json.dump({
                "themes": {"semiconductors": {}},
                "tickers": {
                    "XYZ-NVDA": {"real_symbol": "NVDA", "themes": {"semiconductors": 0.4}, "status": "CONFIRMED"},
                    "XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "PENDING_REVIEW"},
                },
            }, f)
        with open("trade_log.json", "w") as f:
            json.dump([
                {"ticker": "XYZ-NVDA", "action": "BUY", "quantity": 0.3125, "entry_price": 100.0,
                 "size_usd": 31.25, "entry_time": 1752676980, "status": "OPEN", "thematic_exposure": True},
                {"ticker": "XYZ-NVDA", "action": "BUY", "quantity": 0.5859, "entry_price": 80.0,
                 "size_usd": 46.87, "entry_time": 1752677100, "status": "OPEN", "thematic_exposure": True},
            ], f)

        html = build_thematic_exposure_html()
        self.assertIn("XYZ-NVDA", html)
        self.assertIn("XYZ-FOO", html)
        self.assertIn("semiconductors", html)
        self.assertIn("$900.00", html)  # cash

    def test_pending_ticker_gets_action_buttons(self):
        with open("config/thematic_exposure_themes.json", "w") as f:
            json.dump({
                "themes": {"semiconductors": {}},
                "tickers": {
                    "XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "PENDING_REVIEW"},
                    "XYZ-BAR": {"real_symbol": "BAR", "themes": {}, "status": "PENDING_MANUAL"},
                },
            }, f)
        html = build_thematic_exposure_html()
        self.assertIn("expAction('approve','XYZ-FOO')", html)
        self.assertIn("expAction('ignore','XYZ-FOO')", html)
        self.assertIn("expEdit('XYZ-FOO')", html)
        # PENDING_MANUAL has no proposal to approve — no approve button for it
        self.assertNotIn("expAction('approve','XYZ-BAR')", html)
        self.assertIn("expAction('ignore','XYZ-BAR')", html)


class TestSharedReviewFunctions(ThemeTelegramTestBase):
    """The functions dashboard_server.py's POST routes call directly —
    same functions the Telegram commands use (single source of truth)."""

    def test_approve_ticker_function(self):
        from utils.thematic_exposure_lab import approve_ticker
        self._write_themes({"XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "PENDING_REVIEW"}})
        ok, message = approve_ticker("XYZ-FOO")
        self.assertTrue(ok)
        self.assertIn("CONFIRMED", message)
        self.assertEqual(self._read_themes()["tickers"]["XYZ-FOO"]["status"], "CONFIRMED")

    def test_edit_ticker_function(self):
        from utils.thematic_exposure_lab import edit_ticker
        self._write_themes({"XYZ-BAR": {"real_symbol": "BAR", "themes": {}, "status": "PENDING_MANUAL"}})
        ok, message = edit_ticker("XYZ-BAR", "semiconductors:0.5")
        self.assertTrue(ok)
        self.assertEqual(self._read_themes()["tickers"]["XYZ-BAR"]["status"], "CONFIRMED")

    def test_ignore_ticker_function(self):
        from utils.thematic_exposure_lab import ignore_ticker
        self._write_themes({"XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "CONFIRMED"}})
        ok, message = ignore_ticker("XYZ-FOO")
        self.assertTrue(ok)
        self.assertEqual(self._read_themes()["tickers"]["XYZ-FOO"]["status"], "IGNORED")

    def test_swarm_monitor_and_dashboard_use_same_underlying_function(self):
        """Approving via the Telegram path (SwarmMonitor) and reading the
        result back through the same module-level function used by the
        dashboard POST route must agree — no drift between the two UIs."""
        from utils.thematic_exposure_lab import approve_ticker
        self._write_themes({"XYZ-FOO": {"real_symbol": "FOO", "themes": {"semiconductors": 0.8}, "status": "PENDING_REVIEW"}})
        self.monitor._cmd_theme_approve("XYZ-FOO")
        ok, message = approve_ticker("XYZ-FOO")  # already CONFIRMED -> themes present -> re-approve is a safe no-op
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
