import logging
import json
import re
from typing import Dict, List, Optional
from utils.llm_client import LLMClient

from utils.dashboard_query_layer import DashboardDataProvider

class NarrativeGenerator:
    """
    Generates a structured 'Business Case' for a trade proposal using an LLM.
    Enforces the "Defense Protocol": No trade is valid without a clearly articulated Bear Case (Anti-Thesis).
    """

    def __init__(self):
        self.logger = logging.getLogger("Narrator")
        try:
            self.llm = LLMClient(model_name="gemini-3-flash-preview")
            self.dashboard_provider = DashboardDataProvider() # <-- New
        except Exception as e:
            self.logger.critical(f"Failed to initialize Client for Narrator: {e}")
            self.llm = None
            self.dashboard_provider = None

    def generate_business_case(self, ticker: str, action: str, details: Dict, conflicts: List, risk_status: str) -> Dict:
        """
        Constructs the narrative structure: Thesis (Why), Anti-Thesis (Why Not), Synthesis (Conclusion).
        Uses LLM to generate 'Soulful' and reasoning-based text.
        """
        
        # [STATUS CHECK]
        if self.dashboard_provider:
            self.dashboard_provider.update_agent_status(
                "Narrator", "ACTIVE", 
                task=f"Writing Business Case for {ticker}", 
                reasoning="Drafting Thesis & Anti-Thesis..."
            )
        
        # 1. Gather raw inputs
        tech = details.get('technical', {})
        fund = details.get('fundamental', {})
        sent = details.get('sentiment', {})
        
        context_str = f"""
        TICKER: {ticker}
        ACTION: {action}
        RISK_STATUS: {risk_status}
        
        TECHNICAL ANALYSIS:
        Signal: {tech.get('signal', 0)}
        Reason: {tech.get('reason', 'N/A')}
        
        FUNDAMENTAL ANALYSIS:
        Signal: {fund.get('signal', 0)}
        Reason: {fund.get('reason', 'N/A')}
        
        SENTIMENT ANALYSIS:
        Signal: {sent.get('signal', 0)}
        Reason: {sent.get('metrics', {}).get('rationale', 'N/A')}
        
        CONFLICTS/DISAGREEMENTS:
        {json.dumps(conflicts, indent=2) if conflicts else "None. Consensus achieved."}
        """

        prompt = f"""
        You are the 'Narrator' of an elite algorithmic trading fund. 
        Your job is to write a compelling, high-stakes Business Case for the following trade.
        
        CONTEXT:
        {context_str}
        
        TASK:
        Generate a 3-part narrative. You MUST be objective, professional, yet sharp and distinct.
        Avoid generic AI fluff. Use trader terminology.
        
        Part 1: THESIS (The Bull Case for BUY, Bear Case for SELL)
        - Why is this a good trade right now? What is the edge?
        
        Part 2: ANTI-THESIS (The Risk / The Bear Case)
        - You act as the Devil's Advocate. Destroy the trade idea. 
        - detecting weaknesses in the data or macro environment.
        - FAILURE TO IDENTIFY RISK IS FATAL.
        
        Part 3: SYNTHESIS (The Verdict)
        - Weigh the Thesis vs Anti-Thesis.
        - Why do we proceed despite the risks? Or do we?
        - Incorporate the Risk Status ({risk_status}).
        
        OUTPUT FORMAT (JSON):
        {{
            "thesis": "...",
            "anti_thesis": "...",
            "synthesis": "..."
        }}
        """

        try:
            if not self.llm:
                raise RuntimeError("LLM not available")

            response_text = self.llm.analyze_text(prompt, agent_name="Narrator")
            
            # Clean and parse JSON
            cleaned_text = self._clean_json_text(response_text)
            response_data = json.loads(cleaned_text)
            
            thesis = response_data.get("thesis", "Failed to generate Thesis.")
            anti_thesis = response_data.get("anti_thesis", "Failed to generate Anti-Thesis.")
            synthesis = response_data.get("synthesis", "Failed to generate Synthesis.")
            
            # Validation
            is_valid = len(anti_thesis) > 20 # Ensure meaningful risk assessment
            status = "VALID" if is_valid else "INVALID_NO_RISK_IDENTIFIED"
            
            if not is_valid:
                self.logger.warning(f"Trade for {ticker} flagged: Weak Anti-Thesis generated.")

            return {
                "title": f"{action} Opportunity: {ticker}",
                "thesis": thesis,
                "anti_thesis": anti_thesis,
                "synthesis": synthesis,
                "narrative_status": status
            }

        except Exception as e:
            self.logger.error(f"Narrative generation failed: {e}")
            # Fallback (Should ideally be a hard fail as per requirements, but we iterate)
            raise RuntimeError(f"Narrative Generation Failed: {e}") # Fail loud

    def _clean_json_text(self, text: str) -> str:
        """Helper to extract JSON from markdown code blocks if present."""
        text = text.strip()
        if "```json" in text:
            pattern = r"```json(.*?)```"
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()
        elif "```" in text:
             pattern = r"```(.*?)```"
             match = re.search(pattern, text, re.DOTALL)
             if match:
                return match.group(1).strip()
        return text
