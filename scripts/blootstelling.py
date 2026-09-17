"""Blootstellingsmeting: hangt het vermogen aan één factor, en wat kost een daling van 20%?

    python scripts/blootstelling.py --stand stand.json

`stand.json` haal je van de VM (de potjes en de open posities staan daar):

    gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker exec \\
      -w /app agent_trader_swarm python3 -c "import json;n=json.load(open(\\"data/sleeve_nav.json\\"));\\
      h=n[\\"history\\"][-1];p=json.load(open(\\"thematic_exposure_positions.json\\"));\\
      print(json.dumps({\\"potjes\\":h[\\"sleeves\\"],\\"dip\\":{k:v[\\"current_value_usd\\"] \\
      for k,v in p.items() if v.get(\\"status\\")==\\"OPEN\\"}}))"'

**De valkuil die deze meting bijna onbruikbaar maakte** (2026-09-17): WEBN sluit om 17:30 in
Frankfurt, Amerikaanse aandelen om 22:00. Op dagkoersen meet je dan langs elkaar heen: de
beta van de dip-koper kwam uit op 0,33 terwijl hij op weekbasis 1,08 is. Meet daarom
wekelijks, en tel de vertraagde marktbeweging mee (Dimson). Maandkoersen geven te weinig
punten (24 in twee jaar) en leveren onzin op.
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd

BENCH = "WEBN.DE"          # het fonds dat we echt bezitten; noteert in euro's
JAREN = "2y"
# Beurs-tickers per dip-koper-positie (de sleeve handelt ze als XYZ-perp op HL).
TICKER = {"XYZ-BABA": "BABA", "XYZ-ORCL": "ORCL", "XYZ-TSLA": "TSLA", "XYZ-INTC": "INTC",
          "XYZ-AVGO": "AVGO", "XYZ-GOOGL": "GOOGL", "XYZ-NVDA": "NVDA", "XYZ-AMD": "AMD",
          "XYZ-MSFT": "MSFT", "XYZ-AAPL": "AAPL", "XYZ-META": "META", "XYZ-AMZN": "AMZN"}
RENTE = ("yield_core", "swarm", "house", "basis")     # USDC: geen marktrisico, wel protocolrisico


def _dimson_beta(y: pd.Series, x: pd.Series) -> tuple:
    """(beta, Dimson-beta, correlatie). Dimson telt de vertraagde markt mee."""
    xx = x.reindex(y.index).dropna()
    y = y.reindex(xx.index)
    # ddof=1 aan beide kanten: np.cov is een steekproefschatter, np.var standaard niet.
    # Zonder dit is de beta n/(n-1) te hoog (bij 104 weken ~1%).
    beta = np.cov(y, xx)[0, 1] / np.var(xx, ddof=1)
    xl = xx.shift(1).dropna()
    yy, xc = y.reindex(xl.index), xx.reindex(xl.index)
    A = np.column_stack([np.ones(len(xl)), xc, xl])
    coef = np.linalg.lstsq(A, yy, rcond=None)[0]
    return beta, coef[1] + coef[2], float(np.corrcoef(y, xx)[0, 1])


def meet(stand: dict, schok: float = -0.20) -> dict:
    import yfinance as yf

    dip = {TICKER[k]: v for k, v in stand.get("dip", {}).items() if k in TICKER}
    onbekend = [k for k in stand.get("dip", {}) if k not in TICKER]
    if onbekend:
        print("LET OP: geen beurs-ticker voor %s — die posities tellen NIET mee" % onbekend)
    kern = stand.get("kern", {"BTC-USD": 0.0, "ETH-USD": 0.0})
    tickers = list(dip) + [t for t, w in kern.items() if w] + [BENCH, "EURUSD=X"]
    ruw = yf.download(tickers, period=JAREN, interval="1d", auto_adjust=True,
                      progress=False)["Close"].ffill()
    koers = pd.DataFrame(index=ruw.index)
    koers[BENCH] = ruw[BENCH] * ruw["EURUSD=X"]          # naar USD
    for t in tickers[:-2]:
        koers[t] = ruw[t]
    week = koers.dropna().resample("W-FRI").last().dropna()
    rend = week.pct_change().dropna()

    def mandje(gew):
        gew = {k: v for k, v in gew.items() if v}
        if not gew:
            return None
        w = pd.Series(gew) / sum(gew.values())
        return (week[list(gew)].pct_change() * w).sum(axis=1).reindex(rend.index).dropna()

    uit = {"periode": [str(rend.index[0].date()), str(rend.index[-1].date())], "weken": len(rend),
           "beta": {}, "potjes": stand["potjes"], "schok": schok}
    for naam, serie in (("dip-koper", mandje(dip)), ("crypto vasthouden", mandje(kern))):
        if serie is None or serie.empty:
            uit["beta"][naam] = None
            continue
        b, bd, c = _dimson_beta(serie, rend[BENCH])
        uit["beta"][naam] = {"beta": round(b, 2), "dimson": round(bd, 2), "corr": round(c, 2),
                             "jaarvol_pct": round(float(serie.std() * np.sqrt(52) * 100))}
    return uit


def rapport(m: dict) -> None:
    p = m["potjes"]
    totaal = sum(p.values())
    print("Blootstelling — %d weken (%s .. %s), benchmark %s in USD"
          % (m["weken"], m["periode"][0], m["periode"][1], BENCH))
    for naam, b in m["beta"].items():
        if b is None:
            print("  %-20s onmeetbaar" % naam)
        else:
            print("  %-20s beta %.2f (Dimson %.2f) · corr %.2f · jaarvol %d%%"
                  % (naam, b["beta"], b["dimson"], b["corr"], b["jaarvol_pct"]))
    beta_van = {"thematic_exposure": m["beta"].get("dip-koper"),
                "conviction_core": m["beta"].get("crypto vasthouden")}
    print("\nStress: wereldindex %+.0f%%, de rest volgens gemeten Dimson-beta" % (m["schok"] * 100))
    verlies, onmeetbaar = 0.0, []
    for sleutel, waarde in sorted(p.items(), key=lambda kv: -kv[1]):
        if not waarde:
            continue
        if sleutel in RENTE:
            v = 0.0
        elif sleutel == "tradfi":
            v = waarde * m["schok"]
        elif sleutel in beta_van:
            b = beta_van[sleutel]
            if b is None:
                onmeetbaar.append(sleutel)
                continue
            v = waarde * m["schok"] * b["dimson"]
        else:
            onmeetbaar.append(sleutel)
            continue
        verlies += v
        print("  %-22s $%8.2f (%4.1f%%) -> %+8.2f" % (sleutel, waarde, waarde / totaal * 100, v))
    if onmeetbaar:
        print("  ONMEETBAAR: %s — deze potjes staan NIET in het totaal hieronder" % onmeetbaar)
    print("  %-22s $%8.2f          -> %+8.2f = %.1f%% van het vermogen"
          % ("TOTAAL", totaal, verlies, verlies / totaal * 100))
    risico = sum(v for k, v in p.items() if k not in RENTE)
    print("\nRisicodragend $%.0f (%.0f%%) · rentedragend $%.0f (%.0f%%)"
          % (risico, risico / totaal * 100, totaal - risico, (totaal - risico) / totaal * 100))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--stand", required=True, help="JSON met {potjes, dip, kern}")
    args = ap.parse_args(argv)
    with open(args.stand, encoding="utf-8") as fh:
        stand = json.load(fh)
    if "potjes" not in stand:
        raise SystemExit("stand.json mist 'potjes' — meet liever niets dan iets verkeerds")
    rapport(meet(stand))
    return 0


if __name__ == "__main__":
    sys.exit(main())
