"""Inventaris van één wallet over alle ketens waar hij actief is.

    python scripts/wallet_inventaris.py [adres]
    python scripts/wallet_inventaris.py --snel        # ongeprijsde tokens overslaan (dan is het totaal een ondergrens)

## Waarom dit bestaat

Op 2026-08-23 is deze wallet drie keer achter elkaar verkeerd ingeschat, en telkens
door dezelfde denkfout: **afwezigheid van data behandelen als een meting.**

1. Alleen Ethereum bekeken en over "de wallet" geconcludeerd. Het adres blijkt op
   ZEVEN ketens actief.
2. Eén bron vertrouwd. Ethplorer gaf 126 posities, Blockscout 232 op dezelfde keten.
3. "Geen prijs" gelezen als "waardeloos" en 114 tokens afgeschreven — waarna de
   eigenaar terecht wees op LIGHT (BSC), $435 en volledig liquide.

Dit script maakt die drie fouten structureel onmogelijk: het loopt alle ketens af,
noemt zijn bron per keten, en houdt "niet uitgelezen" apart van "waardeloos".

## De indeling van tokens

| groep | betekenis |
|---|---|
| met koers | de bron kent een koers — telt mee in het totaal |
| lokaas | de NAAM is een URL of een claim-instructie. NOOIT aanraken: die tokens bestaan om je naar een kwaadaardig contract te lokken zodra je ze probeert te verkopen |
| geen koers | gewoon project, alleen (nog) geen koers bij deze bron. NIET hetzelfde als waardeloos — LIGHT zat in deze groep |
| niet uitgelezen | de bron gaf een fout. GEEN oordeel, telt nergens in mee |

## Bronnen en hun grenzen

Blockscout heeft publieke instanties voor Ethereum, Base, Optimism, Polygon,
Arbitrum en Gnosis. Voor **BSC en Avalanche bestaat die niet** — daar wordt alleen
het native saldo plus expliciet bekende tokens gelezen, en dat wordt als
ONVOLLEDIG gemeld. Dat is geen tekortkoming om weg te poetsen: het is precies het
soort gat dat de eerste inventarisatie fout maakte.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

STANDAARD_ADRES = "0x75a70b3f24eb6f32e75b53fbe9315111d05851d0"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
RPC_UA = dict(UA, **{"Content-Type": "application/json"})

# Lokaas herken je aan de NAAM, niet aan het ontbreken van een koers.
LOKAAS = re.compile(
    r"(https?://|www\.|\.(io|com|net|xyz|site|fi|org|club|pro|finance|gifts?)\b"
    r"|visit |claim |airdrop|reward|voucher|gift|free )", re.I)

# Wikkels die 1:1 met de native munt lopen maar waar de indexer geen koers voor heeft.
EEN_OP_EEN_MET_NATIVE = {"Blur Pool"}

KETENS = [
    # naam,        rpc,                                              blockscout,                        munt,   coingecko-id
    ("Ethereum",  "https://ethereum.publicnode.com",                 "https://eth.blockscout.com",      "ETH",  "ethereum"),
    ("BSC",       "https://bsc-dataseed.binance.org",                None,                              "BNB",  "binancecoin"),
    ("Polygon",   "https://polygon-bor-rpc.publicnode.com",          "https://polygon.blockscout.com",  "POL",  "matic-network"),
    ("Base",      "https://base-rpc.publicnode.com",                 "https://base.blockscout.com",     "ETH",  "ethereum"),
    ("Arbitrum",  "https://arbitrum.gateway.tenderly.co",            "https://arbitrum.blockscout.com", "ETH",  "ethereum"),
    ("Optimism",  "https://optimism-rpc.publicnode.com",             "https://optimism.blockscout.com", "ETH",  "ethereum"),
    ("Avalanche", "https://avalanche-c-chain-rpc.publicnode.com",    None,                              "AVAX", "avalanche-2"),
    ("Gnosis",    "https://rpc.gnosischain.com",                     "https://gnosis.blockscout.com",   "XDAI", "xdai"),
]

# Tokens die we op een keten ZONDER indexer expliciet kennen. Groeit met de hand:
# beter een korte eerlijke lijst dan een stilzwijgend gat.
HANDMATIG = {
    "BSC": [("LIGHT", "0x477c2c0459004e3354ba427fa285d7c053203c0e")],
}


def _post(url, body, timeout=25):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=RPC_UA)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _get(url, timeout=30):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout))


def rpc(url, method, params):
    j = _post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in j:
        raise RuntimeError(j["error"])
    return j["result"]


def erc20_saldo(rpc_url, token, houder):
    data = "0x70a08231" + houder.lower().replace("0x", "").rjust(64, "0")
    ruw = rpc(rpc_url, "eth_call", [{"to": token, "data": data}, "latest"])
    dec = int(rpc(rpc_url, "eth_call", [{"to": token, "data": "0x313ce567"}, "latest"]), 16)
    return int(ruw, 16) / (10 ** dec)


def dex_prijs(token):
    """DexScreener: koers EN pool-liquiditeit. Die tweede is bij long-tail tokens
    de vraag die telt — een koers zonder pool is geen prijs."""
    try:
        d = _get("https://api.dexscreener.com/latest/dex/tokens/%s" % token, 20)
        paren = sorted(d.get("pairs") or [],
                       key=lambda p: -(float((p.get("liquidity") or {}).get("usd") or 0)))
        if not paren:
            return None
        p = paren[0]
        return {"usd": float(p.get("priceUsd") or 0),
                "liq": float((p.get("liquidity") or {}).get("usd") or 0),
                "vol24": float((p.get("volume") or {}).get("h24") or 0)}
    except Exception:
        return None


def native_prijzen(ids):
    for poging in range(4):
        try:
            return _get("https://api.coingecko.com/api/v3/simple/price?ids=%s&vs_currencies=usd"
                        % ",".join(sorted(set(ids))), 25)
        except Exception:
            time.sleep(15 * (poging + 1))
    return {}


def main():
    adres = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("0x") else STANDAARD_ADRES
    print("Wallet: %s\n" % adres)

    snel = "--snel" in sys.argv
    koersen = native_prijzen([k[4] for k in KETENS])
    totaal = 0.0
    onvolledig, groepen, extra = [], {}, []

    for naam, rpc_url, bs, munt, cg in KETENS:
        try:
            bal = int(rpc(rpc_url, "eth_getBalance", [adres, "latest"]), 16) / 1e18
            n_tx = int(rpc(rpc_url, "eth_getTransactionCount", [adres, "latest"]), 16)
        except Exception as e:
            print("%-10s  RPC onbereikbaar (%s) — GEEN oordeel" % (naam, str(e)[:40]))
            onvolledig.append("%s (RPC)" % naam)
            continue

        pr = (koersen.get(cg) or {}).get("usd")
        nat_usd = bal * pr if pr else None
        if nat_usd:
            totaal += nat_usd
        print("%-10s  %s %.6f%s   %d tx" % (
            naam, munt, bal, ("  = $%.2f" % nat_usd) if nat_usd else "  (koers onbekend)", n_tx))

        # ── tokens ────────────────────────────────────────────────────────────
        met_koers, lokaas, geen_koers = [], [], []
        if bs:
            try:
                d = _get("%s/api/v2/addresses/%s/token-balances" % (bs, adres), 40)
            except Exception as e:
                print("            tokens NIET uitgelezen (%s) — GEEN oordeel" % str(e)[:40])
                onvolledig.append("%s (tokens)" % naam)
                d = []
            for x in d:
                t = x.get("token") or {}
                if t.get("type") != "ERC-20":
                    continue
                dec = int(t.get("decimals") or 0)
                b = int(x["value"]) / (10 ** dec) if x.get("value") else 0.0
                sym, nm = t.get("symbol") or "?", t.get("name") or ""
                rate = t.get("exchange_rate")
                if rate:
                    w = b * float(rate)
                    met_koers.append((w, sym, b, float(rate)))
                    totaal += w
                elif nm in EEN_OP_EEN_MET_NATIVE and pr:
                    # Blur Pool (bETH) is 1:1 met ETH maar heeft bij Blockscout geen
                    # koers. De eerste versie liet hem daardoor uit het TOTAAL vallen
                    # -- $6.356, de vierde grootste post. Dezelfde fout als hierboven,
                    # nu in de optelling in plaats van in de indeling.
                    w = b * pr
                    met_koers.append((w, "%s (1:1 %s)" % (sym or nm, munt), b, pr))
                    totaal += w
                elif LOKAAS.search(nm + " " + sym):
                    lokaas.append(sym)
                else:
                    geen_koers.append((sym, b, t.get("address_hash")))
        else:
            onvolledig.append("%s (geen indexer — alleen native + bekende tokens)" % naam)
            for sym, contract in HANDMATIG.get(naam, []):
                try:
                    b = erc20_saldo(rpc_url, contract, adres)
                    m = dex_prijs(contract)
                    if m and m["usd"]:
                        met_koers.append((b * m["usd"], sym, b, m["usd"]))
                        totaal += b * m["usd"]
                    else:
                        geen_koers.append((sym, b, contract))
                except Exception:
                    onvolledig.append("%s/%s" % (naam, sym))

        for w, sym, b, rate in sorted(met_koers, reverse=True)[:6]:
            if w >= 1:
                print("            %-10s %16.4f x $%-12.8f = $%.2f" % (sym, b, rate, w))
        rest = sum(w for w, *_ in met_koers if w < 1)
        if rest:
            print("            (+ %d posities onder $1)" % sum(1 for w, *_ in met_koers if w < 1))
        if geen_koers or lokaas:
            print("            %d zonder koers · %d lokaas-patroon (nooit aanraken)"
                  % (len(geen_koers), len(lokaas)))
        # Ongeprijsde posities NIET stil laten verdwijnen. Sorteren op SALDO is
        # zinloos (spam-tokens hebben triljoenen), dus we prijzen ze gewoon bij
        # DexScreener. Dat maakt het totaal compleet in plaats van een ondergrens
        # die van de dekking van één indexer afhangt.
        if not snel:
            for sym, b, adr in geen_koers:
                if not adr or b <= 0:
                    continue
                m = dex_prijs(adr)
                time.sleep(0.5)
                if m and m["usd"] and b * m["usd"] >= 1:
                    w = b * m["usd"]
                    totaal += w
                    extra.append((w, naam, sym, b, m["usd"], m["liq"], m["vol24"]))
                    print("              + %-12s %16.4f x $%-12.8f = $%-9.2f pool $%.0f"
                          % (str(sym)[:12], b, m["usd"], w, m["liq"]))
        groepen[naam] = {"geen_koers": geen_koers, "lokaas": lokaas}
        print()

    print("=" * 78)
    print("TOTAAL GEMETEN: $%.2f" % totaal)
    print("=" * 78)
    print("Bevat NIET: NFT's. Die staan apart in scripts/nft_wallet_scan.py, want")
    print("floor x stuks is een bovengrens die je bij verkoop niet haalt.")
    if onvolledig:
        print("ONVOLLEDIG — hier is NIET gemeten, dus dit is een ONDERGRENS:")
        for o in onvolledig:
            print("   · %s" % o)
    zk = sum(len(g["geen_koers"]) for g in groepen.values())
    lk = sum(len(g["lokaas"]) for g in groepen.values())
    print("")
    print("%d tokens zonder koers bij de indexer — bij DexScreener nagekeken." % zk)
    print("%d tokens met een lokaas-naam (URL of claim-instructie). Nooit aanraken." % lk)

    if extra:
        print("")
        print("Via DexScreener alsnog geprijsd: %d posities, samen $%.2f"
              % (len(extra), sum(x[0] for x in extra)))
        print("LET OP: waarde zonder pool-liquiditeit is niet te verzilveren.")
    if snel:
        print("")
        print("--snel: ongeprijsde tokens NIET opgezocht — het totaal is dan een ONDERGRENS.")


if __name__ == "__main__":
    main()
