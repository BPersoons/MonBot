"""NAV — één totaalbeeld van al het vermogen.

    python -m utils.nav

Waarom dit bestaat: er was geen enkele plek waar het totaal stond. `treasury_state.
total_portfolio` telde de dip-koper-sleeve en het crypto-vasthouden niet mee en
rapporteerde daardoor ~14% te weinig ($2.644 tegen werkelijk ~$3.081, gemeten
2026-08-12).

⚠️ Correctie op een eerdere versie van deze tekst: hier stond dat het kasbeheer
percentages over die noemer verdeelt en dat het dus meer dan een rapportagefout is.
Dat klopt niet. De TreasuryAgent rekent met `hl_balance + yield_bal +
treasury_usdc` — precies het VRIJE kapitaal, en dat is de juiste noemer voor zijn
taak. Het crypto-potje (spot-tokens) en de dip-koper (eigen wallet, eigen budget)
zijn al toegewezen en horen daar niet in. Deze module lost dus een rapportagegat
op, niet een allocatiefout.

## De regel die dit bestand draagt

**Een mislukte uitlezing telt NOOIT als $0.**

Bij een netwerkfout of een API-hik zou een potje anders uit de NAV verdwijnen, en
dat ziet eruit als een plotseling verlies. CLAUDE.md waarschuwt daar expliciet voor
(`RiskManager.check_portfolio_drawdown` kan op zoiets een valse noodstop geven).
Daarom krijgt elk potje een `status`, en draagt het totaal een `compleet`-vlag.
Wie dit getal gebruikt om te beslissen, hoort eerst `compleet` te lezen.
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("NAV")

NAV_FILE = "nav.json"
SLEEVE_FILE = "thematic_exposure_positions.json"
TREASURY_STATE = "treasury_state.json"

# Welke spot-tokens horen bij "crypto vasthouden" (Conviction Core).
_VASTHOUD_COINS = {"UBTC": "BTC", "UETH": "ETH"}


def _potje(sleutel, label, waarde, status="ok", detail="", bron=""):
    return {"sleutel": sleutel, "label": label, "waarde_usd": waarde,
            "status": status, "detail": detail, "bron": bron}


def _perp_marks(coins=("BTC", "ETH")):
    """Mark-prijzen van de perp-markt. {coin: prijs}, ontbrekend = niet opgenomen.

    WAAROM NIET get_spot_price(): dat is op Hyperliquid onbetrouwbaar. ccxt mapt
    `BTC/USDC` naar spot-paar `@50`, en dat is FRAC/USDC — een token van $0,024,
    niet Bitcoin. `UBTC/USDC` mapt naar hetzelfde. De spot-tokennamen in HL's
    metadata zijn niet bruikbaar om het onderliggende te herkennen (het paar dat
    wél op $63.670 handelt heet daar "NEKO").

    De perp-mark is liquide, canoniek en week op 2026-08-12 0,05% af van de echte
    spot-mid (BTC $63.700 vs $63.670). Voor het waarderen van spot-BTC/ETH is dat
    ruim voldoende; de basis is verwaarloosbaar naast de meetfout die we hiermee
    oplossen. Dit beantwoordt de openstaande vraag in PLAN_2026-08 par. 7.
    """
    import json as _json
    import urllib.request

    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info",
        data=_json.dumps({"type": "metaAndAssetCtxs"}).encode(),
        headers={"Content-Type": "application/json"})
    meta, ctxs = _json.loads(urllib.request.urlopen(req, timeout=20).read())
    uit = {}
    for i, a in enumerate(meta["universe"]):
        if a["name"] in coins:
            px = ctxs[i].get("markPx")
            if px:
                uit[a["name"]] = float(px)
    return uit


def _hyperliquid(ex):
    """Handelsmarge (USDC-equity) én de spot-tokens van het vasthoud-potje.

    get_balance() geeft de USDC-equity van het unified account. De UBTC/UETH van
    Conviction Core zijn APARTE spot-tokens en zitten daar NIET in — precies de
    reden dat het vasthoud-potje buiten elke rapportage viel.
    """
    potjes = []
    try:
        equity = float(ex.get_balance() or 0.0)
        potjes.append(_potje("handelsmarge", "Hyperliquid — USDC (marge + kas)",
                             round(equity, 2), bron="get_balance()"))
    except Exception as e:
        potjes.append(_potje("handelsmarge", "Hyperliquid — USDC (marge + kas)", None,
                             status="fout", detail=str(e)[:120], bron="get_balance()"))

    bron = "get_spot_holdings() + perp markPx"
    try:
        holdings = ex.get_spot_holdings() or {}
        marks = _perp_marks()
        totaal, stukken = 0.0, []
        for coin, basis in _VASTHOUD_COINS.items():
            qty = float(holdings.get(coin, 0.0) or 0.0)
            if qty <= 0:
                continue
            prijs = marks.get(basis)
            if not prijs:
                raise ValueError("geen mark-prijs voor %s" % basis)
            totaal += qty * prijs
            stukken.append("%s %.6f à $%s" % (basis, qty, format(round(prijs), ",d")))
        potjes.append(_potje("crypto_vasthouden", "Crypto vasthouden (BTC/ETH spot)",
                             round(totaal, 2), detail=" · ".join(stukken), bron=bron))
    except Exception as e:
        potjes.append(_potje("crypto_vasthouden", "Crypto vasthouden (BTC/ETH spot)", None,
                             status="fout", detail=str(e)[:120], bron=bron))
    return potjes


def _rente_en_kas():
    """Aave en andere renteprotocollen, plus losse USDC op de treasury-wallet."""
    potjes = []
    try:
        from utils.treasury_executor import (get_total_yield_balance,
                                             get_arb_usdc_balance, _TREASURY_WALLET)
    except Exception as e:
        return [_potje("veilig", "Veilig — Aave en renteprotocollen", None,
                       status="fout", detail="import faalde: %s" % str(e)[:90]),
                _potje("treasury_kas", "USDC op de treasury-wallet", None,
                       status="fout", detail="import faalde")]

    try:
        potjes.append(_potje("veilig", "Veilig — Aave en renteprotocollen",
                             round(float(get_total_yield_balance(_TREASURY_WALLET)), 2),
                             bron="get_total_yield_balance()"))
    except Exception as e:
        potjes.append(_potje("veilig", "Veilig — Aave en renteprotocollen", None,
                             status="fout", detail=str(e)[:120]))
    try:
        potjes.append(_potje("treasury_kas", "USDC op de treasury-wallet",
                             round(float(get_arb_usdc_balance(_TREASURY_WALLET)), 2),
                             bron="get_arb_usdc_balance()"))
    except Exception as e:
        potjes.append(_potje("treasury_kas", "USDC op de treasury-wallet", None,
                             status="fout", detail=str(e)[:120]))
    return potjes


def _dip_koper():
    """Thematic sleeve: open posities plus kas, uit zijn eigen statebestand.

    Bewust uit het bestand en niet van de keten: de lab schrijft het elke cyclus bij
    en een extra wallet-uitlezing zou de NAV traag en brozer maken. Wel de ouderdom
    meegeven, zodat een vastgelopen sleeve zichtbaar wordt in plaats van stil.
    """
    try:
        with open(SLEEVE_FILE, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as e:
        return [_potje("dip_koper", "Dip-koper (thema-sleeve)", None,
                       status="fout", detail=str(e)[:120], bron=SLEEVE_FILE)]

    posities = d.get("positions") or {}
    rij = posities.values() if isinstance(posities, dict) else posities
    open_pos = [p for p in rij if str(p.get("status", "")).upper() != "CLOSED"]
    waarde = sum(float(p.get("current_value_usd") or 0.0) for p in open_pos)
    kas = float(d.get("cash_usd") or 0.0)

    laatste = max((str(p.get("last_updated") or "") for p in open_pos), default="")
    return [_potje("dip_koper", "Dip-koper (thema-sleeve)", round(waarde + kas, 2),
                   detail="%d open posities $%.2f + kas $%.2f%s"
                          % (len(open_pos), waarde, kas,
                             " · laatst bijgewerkt %s" % laatste[:16] if laatste else ""),
                   bron=SLEEVE_FILE)]


def compute_nav(exchange=None):
    """Het volledige beeld. Faalt nooit in zijn geheel; markeert wat ontbreekt."""
    potjes = []

    ex = exchange
    if ex is None:
        try:
            from utils.exchange_client import HyperliquidExchange
            ex = HyperliquidExchange()
        except Exception as e:
            logger.warning("NAV: geen exchange-client (%s)", e)
    if ex is not None:
        potjes.extend(_hyperliquid(ex))
    else:
        potjes.append(_potje("handelsmarge", "Hyperliquid — USDC (marge + kas)", None,
                             status="fout", detail="geen exchange-client"))
        potjes.append(_potje("crypto_vasthouden", "Crypto vasthouden (BTC/ETH spot)", None,
                             status="fout", detail="geen exchange-client"))

    potjes.extend(_rente_en_kas())
    potjes.extend(_dip_koper())

    gelukt = [p for p in potjes if p["status"] == "ok" and p["waarde_usd"] is not None]
    mislukt = [p for p in potjes if p["status"] != "ok"]
    totaal = round(sum(p["waarde_usd"] for p in gelukt), 2)

    for p in gelukt:
        p["aandeel_pct"] = round(p["waarde_usd"] / totaal * 100, 1) if totaal else 0.0

    return {
        "berekend_op": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "totaal_usd": totaal,
        "compleet": not mislukt,
        "ontbrekend": [p["sleutel"] for p in mislukt],
        "waarschuwing": ("" if not mislukt else
                         "ONVOLLEDIG — %d potje(s) niet uitgelezen. Het totaal is een "
                         "ONDERGRENS, geen waarde. Gebruik dit niet voor een "
                         "drawdown-beslissing." % len(mislukt)),
        "potjes": potjes,
    }


def save_nav(nav, pad=NAV_FILE):
    try:
        with open(pad, "w", encoding="utf-8") as fh:
            json.dump(nav, fh, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning("NAV: kon %s niet schrijven (%s)", pad, e)
        return False


def _print(nav):
    print("NAV per %s" % nav["berekend_op"])
    print("-" * 68)
    for p in nav["potjes"]:
        if p["status"] == "ok":
            print("  %-34s $%10.2f  %5.1f%%" % (p["label"], p["waarde_usd"],
                                                p.get("aandeel_pct", 0)))
        else:
            print("  %-34s %11s          !! %s" % (p["label"], "ONBEKEND", p["detail"][:40]))
        if p.get("detail") and p["status"] == "ok":
            print("       %s" % p["detail"][:90])
    print("-" * 68)
    print("  %-34s $%10.2f" % ("TOTAAL", nav["totaal_usd"]))
    if not nav["compleet"]:
        print("\n  %s" % nav["waarschuwing"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    nav = compute_nav()
    _print(nav)
    save_nav(nav)
    print("\nGeschreven naar %s" % NAV_FILE)
