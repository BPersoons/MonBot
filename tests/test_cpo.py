import unittest
from unittest.mock import MagicMock, patch
import json
import os
from agents.product_owner import ProductOwner

class TestProductOwner(unittest.TestCase):
    def setUp(self):
        # Mock Database and LLM
        with patch('agents.product_owner.DatabaseClient') as mock_db, \
             patch('agents.product_owner.LLMClient') as mock_llm:
            
            self.cpo = ProductOwner()
            self.cpo.db = MagicMock()
            self.cpo.db.is_available.return_value = True
            
            self.cpo.llm = MagicMock()
            self.cpo.llm.analyze_text.return_value = '''[
                {
                    "title": "Improve Bear Case Generation",
                    "description": "The logic is failing here.",
                    "impact": 8, "confidence": 7, "ease": 5, "mission_prompt": "Fix it.",
                    "priority": "HIGH"
                }
            ]'''
            
        # Create Dummy Log
        self.test_log = "test_trade_log.json"
        trades = []
        # Create 5 Narrative Failures (Trigger condition is >= 3)
        for i in range(5):
            trades.append({
                "id": f"trade_{i}",
                "status": "REJECTED_BY_NARRATOR",
                "risk_warning": "NARRATIVE_FAIL"
            })
            
        with open(self.test_log, 'w') as f:
            json.dump(trades, f)
            
        self.cpo.trade_log_path = self.test_log

    def tearDown(self):
        if os.path.exists(self.test_log):
            os.remove(self.test_log)

    def test_detect_patterns_and_create_task(self):
        """Test if CPO detects the Narrative Failure pattern."""
        
        # Mock DB select (Check duplicate -> Returns Empty)
        self.cpo.db.client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        
        # Run Analysis
        new_tasks = self.cpo.run_analysis_cycle()
        
        # Expect 1 new task (Improve Bear Case Generation)
        self.assertEqual(new_tasks, 1)
        
        # Verify DB Insert Call
        # We expect one insert call with title "Improve Bear Case Generation"
        args, _ = self.cpo.db.client.table.return_value.insert.call_args
        task_payload = args[0]
        
        print("\n--- TEST CPO TASK CREATION ---")
        print(f"Task Title: {task_payload['title']}")
        print(f"Priority: {task_payload['priority']}")
        
        self.assertEqual(task_payload['title'], "Improve Bear Case Generation")
        self.assertEqual(task_payload['priority'], "HIGH")

if __name__ == '__main__':
    unittest.main()
