from agents.technical_analyst import TechnicalAnalyst
import time

def debug_stagnation():
    ta = TechnicalAnalyst()
    
    tickers = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    results = {}
    
    print("--- STARTING STAGNATION TEST ---")
    
    for t in tickers:
        print(f"\nAnalyzing {t}...")
        res = ta.analyze(t)
        score = res['signal']
        reason = res['reason']
        results[t] = score
        print(f"Result for {t}: Score={score:.2f} | Reason={reason}")
        time.sleep(1)
        
    print("\n--- SUMMARY ---")
    for t, s in results.items():
        print(f"{t}: {s}")
        
    scores = list(results.values())
    if len(set(scores)) == 1:
        print("\nFAIL: All scores are identical! Stagnation confirmed.")
    else:
        print("\nSUCCESS: Scores are different.")

if __name__ == "__main__":
    debug_stagnation()
