# Chaos Test Suite for Adversarial Testing
# Tests the system's resilience against corrupt data and extreme market conditions

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.risk_manager import RiskManager
from core.circuit_breaker import CircuitBreaker
import json
from datetime import datetime

class ChaosTest:
    def __init__(self):
        self.risk_manager = RiskManager()
        self.circuit_breaker = CircuitBreaker()
        self.results = []
        self.passed = 0
        self.failed = 0
        
    def log_result(self, test_name, passed, details):
        # Log test result
        result = {
            "test": test_name,
            "status": "PASSED" if passed else "FAILED",
            "details": details,
            "timestamp": datetime.now().isoformat()
        }
        self.results.append(result)
        
        if passed:
            self.passed += 1
            print(f"PASS {test_name}: PASSED")
        else:
            self.failed += 1
            print(f"FAIL {test_name}: FAILED")
        
        print(f"   Details: {details}")
        print()
    
    def test_corrupt_price_zero(self):
        # Test 1: Corrupt Price Data (price = 0)
        print("Test 1: Corrupt Price Data (price = 0)")
        print("-" * 60)
        
        proposal = {
            "ticker": "BTC/USDT",
            "action": "BUY",
            "price": 0,  # CORRUPT DATA
            "win_probability": 0.6,
            "net_odds": 2.0,
            "analyst_signals": {
                "technical": 0.5,
                "fundamental": 0.3,
                "sentiment": 0.7
            }
        }
        
        result = self.risk_manager.validate_trade_proposal(proposal)
        
        # Expected: Rejected with critical anomaly
        passed = (
            not result['approved'] and
            'anomalies' in result and
            any(a['type'] == 'INVALID_PRICE' for a in result.get('anomalies', []))
        )
        
        self.log_result(
            "Corrupt Price (0) Detection",
            passed,
            f"Approved: {result['approved']}, Reason: {result.get('reason', 'N/A')}"
        )
        
        return passed
    
    def test_extreme_sentiment(self):
        # Test 2: Extreme Sentiment (sentiment = 999)
        print("Test 2: Extreme Sentiment Signal (999)")
        print("-" * 60)
        
        proposal = {
            "ticker": "ETH/USDT",
            "action": "BUY",
            "price": 2500,
            "win_probability": 0.6,
            "net_odds": 2.0,
            "analyst_signals": {
                "technical": 0.5,
                "fundamental": 0.3,
                "sentiment": 999  # CORRUPT DATA
            }
        }
        
        result = self.risk_manager.validate_trade_proposal(proposal)
        
        # Expected: Rejected with critical anomaly
        passed = (
            not result['approved'] and
            'anomalies' in result and
            any(a['type'] in ['EXTREME_SENTIMENT', 'INVALID_SENTIMENT'] for a in result.get('anomalies', []))
        )
        
        self.log_result(
            "Extreme Sentiment (999) Detection",
            passed,
            f"Approved: {result['approved']}, Reason: {result.get('reason', 'N/A')}"
        )
        
        return passed
    
    def test_flash_crash(self):
        # Test 3: Flash Crash Scenario (sudden 50% price drop)
        print("Test 3: Flash Crash Scenario (50% price drop)")
        print("-" * 60)
        
        # First, establish normal price history
        normal_proposals = [
            {"ticker": "BTC/USDT", "price": 80000, "win_probability": 0.6, "net_odds": 2.0, "analyst_signals": {}},
            {"ticker": "BTC/USDT", "price": 81000, "win_probability": 0.6, "net_odds": 2.0, "analyst_signals": {}},
            {"ticker": "BTC/USDT", "price": 79500, "win_probability": 0.6, "net_odds": 2.0, "analyst_signals": {}},
        ]
        
        # Build price history
        for p in normal_proposals:
            self.risk_manager.validate_trade_proposal(p)
        
        # Now send crash proposal
        crash_proposal = {
            "ticker": "BTC/USDT",
            "action": "BUY",
            "price": 40000,  # 50% drop from ~80k
            "win_probability": 0.6,
            "net_odds": 2.0,
            "analyst_signals": {
                "technical": -0.8,
                "fundamental": -0.6,
                "sentiment": -0.9
            }
        }
        
        result = self.risk_manager.validate_trade_proposal(crash_proposal)
        
        # Expected: Rejected with flash crash detection
        passed = (
            not result['approved'] and
            'anomalies' in result and
            any(a['type'] == 'FLASH_CRASH' for a in result.get('anomalies', []))
        )
        
        self.log_result(
            "Flash Crash Detection",
            passed,
            f"Approved: {result['approved']}, Anomalies: {len(result.get('anomalies', []))}"
        )
        
        return passed
    
    def test_invalid_technical_data(self):
        # Test 4: Invalid Technical Indicator (out of range)
        print("Test 4: Invalid Technical Data")
        print("-" * 60)
        
        proposal = {
            "ticker": "SOL/USDT",
            "action": "BUY",
            "price": 100,
            "win_probability": 0.6,
            "net_odds": 2.0,
            "analyst_signals": {
                "technical": 50.0,  # Should be -1 to 1
                "fundamental": 0.3,
                "sentiment": 0.7
            }
        }
        
        result = self.risk_manager.validate_trade_proposal(proposal)
        
        # Expected: Warning anomaly (non-critical but detected)
        passed = 'anomalies' in result and any(
            a['type'] == 'INVALID_TECHNICAL' for a in result.get('anomalies', [])
        )
        
        self.log_result(
            "Invalid Technical Data Detection",
            passed,
            f"Anomalies detected: {len(result.get('anomalies', []))}"
        )
        
        return passed
    
    def test_circuit_breaker_activation(self):
        # Test 5: Circuit Breaker Activation
        print("Test 5: Circuit Breaker Activation on Critical Anomaly")
        print("-" * 60)
        
        # Reset circuit breaker
        self.circuit_breaker.resume_system()
        
        # Send critical anomaly
        proposal = {
            "ticker": "TEST/USDT",
            "action": "BUY",
            "price": -100,  # CRITICAL: Negative price
            "win_probability": 0.6,
            "net_odds": 2.0,
            "analyst_signals": {
                "technical": 0.5,
                "fundamental": 0.3,
                "sentiment": 0.7
            }
        }
        
        result = self.risk_manager.validate_trade_proposal(proposal)
        
        # Check if circuit breaker is now OPEN (can't trade)
        can_trade = self.circuit_breaker.can_trade()
        
        passed = (
            not result['approved'] and
            result.get('circuit_breaker') == 'OPEN' and
            not can_trade
        )
        
        self.log_result(
            "Circuit Breaker Activation",
            passed,
            f"Can Trade: {can_trade}, Circuit Breaker Status: {result.get('circuit_breaker', 'UNKNOWN')}"
        )
        
        # Reset for next tests
        self.circuit_breaker.resume_system()
        
        return passed
    
    def test_circuit_breaker_recovery(self):
        # Test 6: Circuit Breaker Recovery
        print("Test 6: Circuit Breaker Recovery")
        print("-" * 60)
        
        # Set to OPEN
        self.circuit_breaker.pause_system()
        can_trade_before = self.circuit_breaker.can_trade()
        
        # Resume
        self.circuit_breaker.resume_system()
        can_trade_after =  self.circuit_breaker.can_trade()
        
        passed = not can_trade_before and can_trade_after
        
        self.log_result(
            "Circuit Breaker Recovery",
            passed,
            f"Before: {can_trade_before}, After: {can_trade_after}"
        )
        
        return passed
    
    def run_all_tests(self):
        # Run complete test suite
        print("=" * 60)
        print("CHAOS TEST SUITE - ADVERSARIAL TESTING")
        print("=" * 60)
        print()
        
        # Run all tests
        self.test_corrupt_price_zero()
        self.test_extreme_sentiment()
        self.test_flash_crash()
        self.test_invalid_technical_data()
        self.test_circuit_breaker_activation()
        self.test_circuit_breaker_recovery()
        
        # Summary
        print("=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {self.passed + self.failed}")
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"Success Rate: {(self.passed / (self.passed + self.failed) * 100):.1f}%")
        print()
        
        # Save detailed report
        self.save_report()
        
        return self.failed == 0
    
    def save_report(self):
        # Save detailed test report
        report_file = "tests/chaos_test_report.json"
        
        report = {
            "test_suite": "Chaos Test - Adversarial Testing",
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": self.passed + self.failed,
                "passed": self.passed,
                "failed": self.failed,
                "success_rate": (self.passed / (self.passed + self.failed) * 100) if (self.passed + self.failed) > 0 else 0
            },
            "results": self.results
        }
        
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=4)
        
        print(f"Detailed report saved to: {report_file}")
        print()

if __name__ == "__main__":
    tester = ChaosTest()
    success = tester.run_all_tests()
    
    if success:
        print("ALL TESTS PASSED! System is resilient to adversarial inputs.")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED. Review the results above.")
        sys.exit(1)
