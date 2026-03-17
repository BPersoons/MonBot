
import os
import json
import time
import requests
from dotenv import load_dotenv

# Load environment
load_dotenv(".env.adk")
load_dotenv()

HL_WALLET = os.getenv("HL_WALLET_ADDRESS")
HL_KEY = os.getenv("HL_PRIVATE_KEY")
API_URL = "https://api.hyperliquid-testnet.xyz" # Testnet default

def check_hyperliquid():
    print("🏥 HYPERLIQUID DIAGNOSTIC PROBE 🏥")
    print("="*40)
    
    if not HL_WALLET:
        print("❌ CRITICAL: HL_WALLET_ADDRESS not found in environment.")
        return
    else:
        print(f"✅ Wallet Address Found: {HL_WALLET[:6]}...{HL_WALLET[-4:]}")

    # 1. Connectivity Check (Meta)
    print("\n1. Connectivity Check (L1 Info)...")
    try:
        url = f"{API_URL}/info"
        headers = {"Content-Type": "application/json"}
        payload = {"type": "meta"}
        
        start = time.time()
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        latency = (time.time() - start) * 1000
        
        if res.status_code == 200:
            print(f"   ✅ API Alive (Latency: {latency:.0f}ms)")
            data = res.json()
            print(f"   ℹ️ Universe Size: {len(data['universe'])} assets")
        else:
            print(f"   ❌ API Failed: {res.status_code} - {res.text}")
            return
            
    except Exception as e:
        print(f"   ❌ Network Error: {e}")
        return

    # 2. Account Check (Clearinghouse State)
    print("\n2. Account Check (Clearinghouse State)...")
    try:
        payload = {
            "type": "clearinghouseState",
            "user": HL_WALLET
        }
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        
        if res.status_code == 200:
            data = res.json()
            margin_summary = data.get('marginSummary', {})
            account_value = margin_summary.get('accountValue', '0')
            print(f"   ✅ Account Valid")
            print(f"   💰 Account Value: ${account_value}")
            
            positions = data.get('assetPositions', [])
            if positions:
                print(f"   📊 Open Positions: {len(positions)}")
                for p in positions:
                    pos = p.get('position', {})
                    print(f"      - {p.get('coin')}: {pos.get('szi')} units @ {pos.get('entryPx')}")
            else:
                print("   ℹ️ No open positions.")
        else:
            print(f"   ❌ Account Check Failed: {res.status_code} - {res.text}")
    except Exception as e:
         print(f"   ❌ Account Check Error: {e}")

    print("\n" + "="*40)
    print("DIAGNOSTIC COMPLETE")

if __name__ == "__main__":
    check_hyperliquid()
