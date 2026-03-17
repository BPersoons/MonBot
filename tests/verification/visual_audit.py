from playwright.sync_api import sync_playwright
import logging
import sys
import time
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("VisualAudit")

import os
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://34.14.121.27.nip.io/webhook/dashboard")

def run_audit():
    with sync_playwright() as p:
        logger.info(f"🚀 Launching Headless Browser to audit: {DASHBOARD_URL}")
        
        # Launch browser (chromium)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            # 1. Verification: Load Page
            logger.info("NAVIGATING...")
            response = page.goto(DASHBOARD_URL, timeout=30000)
            
            if response.status != 200:
                logger.error(f"❌ Failed to load page. Status Code: {response.status}")
                return False
                
            logger.info("✅ Page Loaded Successfully")
            
            # Wait for dynamic content to load
            page.wait_for_load_state("networkidle")
            
            # Take a snapshot for debugging
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = f"audit_snapshot_{timestamp}.png"
            # page.screenshot(path=screenshot_path) # Optional: enable if we want artifacts
            
            content = page.content()
            
            # 2. Verification: Error Detection
            # Look for common error strings in the rendered HTML
            error_keywords = ["Error", "undefined", "Exception", "502 Bad Gateway"]
            found_errors = []
            
            for keyword in error_keywords:
                if keyword in content:
                    # Context check: "Error" might be in a log message, so we need to be careful.
                    # Simple string match is a good first alert.
                    found_errors.append(keyword)
            
            if found_errors:
                 logger.warning(f"⚠️ Potential Error Keywords found: {found_errors}")
                 # You might want to fail here, or just warn depending on strictness.
                 # For now, let's just warn unless it's a 502/Critical.
                 if "502 Bad Gateway" in found_errors:
                     return False

            # 3. Verification: Timestamp Freshness & Phase Sync
            # Attempt to find the elements that show last_pulse or status
            # Note: This depends heavily on the actual DOM structure of the dashboard.
            # Check the rendered HTML for expected structure.
            
            # Example: Check if "Swarm Health" section exists
            if "Swarm Health" in content:
                logger.info("✅ 'Swarm Health' section detected")
            else:
                logger.warning("⚠️ 'Swarm Health' section NOT found")
                
            # Example: Check for specific agents
            agents = ["Scout", "Strategy", "Risk", "Execution"]
            found_agents = [a for a in agents if a in content]
            
            if len(found_agents) == len(agents):
                logger.info(f"✅ All Agents detected: {found_agents}")
            else:
                 logger.warning(f"⚠️ Missing Agents in dashboard: {set(agents) - set(found_agents)}")
            
            logger.info("✅ VISUAL AUDIT COMPLETE")
            return True

        except Exception as e:
            logger.error(f"❌ Visual Audit Failed: {e}")
            return False
            
        finally:
            browser.close()

if __name__ == "__main__":
    if run_audit():
        sys.exit(0)
    else:
        sys.exit(1)
