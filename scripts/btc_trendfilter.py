"""BTC-trendfilter: haalt in- en uitstappen meer op dan vasthouden?

    python scripts/btc_trendfilter.py

## De vraag

De vorige ronde systematisch crypto-onderzoek eindigde in "geen robuuste alpha"
(memory `feedback_systematic_alpha_hard`, cross-sectionele momentum over 40 assets:
−29,5% over 31 maanden). Dit script stelt een engere vraag: **BTC alleen, één
bekende regel — in de markt boven een voortschrijdend gemiddelde, eruit eronder.**

## Wat dit NIET is

Geen zoektocht naar de beste parameter. Het script draait een REEKS MA-lengtes en
kijkt of de uitkomst over die hele reeks dezelfde kant op wijst. Wint er maar één,
dan is het een gelukstreffer; winnen ze allemaal, dan zit er structuur onder.
Dat onderscheid is precies wat er in augustus 2026 twee keer misging bij de
fondsregels — daar hielden bevindingen op zodra ze op álle paren werden getoetst.

## Wat het WEL is, eerlijk

De drawdown-verbetering is **mechanisch, geen alpha**: een trendfilter vermijdt per
constructie een deel van elke aanhoudende daling. Daarom is hij robuust, en daarom
is hij waarschijnlijker houdbaar dan een rendementsvoordeel. De juiste claim is
"vergelijkbaar rendement tegen minder drawdown", niet "we hebben een edge".

## Drie toetsen die het onderscheid maken

1. **Twee databronnen** — yfinance en Binance. Verdwijnt het effect op de tweede,
   dan was het een data-artefact.
2. **Uitvoeringsvertraging** — handelen op de slotkoers die je ziet (lag 1) versus
   een dag later (lag 2). Crypto handelt 24/7, dus lag 1 is verdedigbaar, maar als
   het voordeel bij lag 2 verdampt is het te fragiel om op te handelen.
3. **Kostengevoeligheid** — 0,05% tot 0,25% per kant. Bij ~10-15 wissels per jaar
   telt dat aan.

## Waarom drawdown hier zwaarder weegt dan rendement

`docs/PLAN_2026-08.md` legt de vloer op **−25%**. BTC vasthouden is historisch −77%
tot −83%. Kopen-en-vasthouden is bij serieuze omvang dus in strijd met de eigen
risicogrens — de vraag is niet alleen "meer rendement" maar "is deze blootstelling
überhaupt te dragen".

Box 3 kent geen vermogenswinstbelasting, dus in- en uitstappen kost fiscaal niets.
Dat nadeel, dat deze aanpak voor de meeste beleggers heeft, geldt hier niet.

## UITKOMST 2026-08-22 — lees dit voordat je het script draait

**Wat standhoudt: de drawdown-halvering. 10 van 10 parameters, op BEIDE bronnen, in
ELK venster.** Volledige historie, out-of-sample vanaf 2021, en het huidige regime
vanaf 2024 — overal beter dan vasthouden. Dat is geen statistisch toeval maar het
mechanische gevolg van uitstappen onder een dalende MA.

**Wat NIET standhoudt: het rendementsvoordeel.** Het brokkelt af zodra je erop drukt:

| toets | beter op rendement |
|---|---|
| volledig, yfinance (2014-) | 10/10 |
| volledig, Binance (2017-) | **4/10** |
| out-of-sample 2021-nu | 7/10 |
| huidig regime 2024-nu | **3/10** |

Zelfde munt, overlappend venster, tegengesteld oordeel — het hangt aan het
startpunt, niet aan een edge. En een **uitvoeringsvertraging van één dag** kost
MA120 een derde van zijn voorsprong (+40,1% -> +28,8%); MA80 zakt er zelfs door
onder vasthouden. Kosten daarentegen doen bijna niets (0,05% vs 0,25%: 2,7pp).

**De eerlijke formulering is dus:** een trendfilter halveert de drawdown van BTC bij
ongeveer gelijk rendement. NIET: het verslaat kopen-en-vasthouden. De hoop dat je
er "slim in en uit" meer uithaalt, wordt door deze cijfers niet gedragen — wat je
koopt is risicoreductie, niet opbrengst.

**Waarom dat toch iets waard is:** BTC vasthouden kent −77% tot −83% drawdown tegen
een planvloer van −25%. MA120 brengt dat naar −28% tot −32%. Dat verandert BTC van
"onhoudbaar binnen mijn eigen grens" in "net houdbaar". Dat is de toepassing.

**Wanneer het de moeite waard wordt:** niet nu. Bij een BTC-positie van ~$130-200
scheelt een gehalveerde drawdown ~$50 in een crash — minder dan de aandacht die het
kost. Dit is een regel om te hanteren zodra de positie groot genoeg is om ertoe te
doen, en hij is met de hand te controleren (9-15 wissels per jaar).
"""

import sys
import warnings

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
warnings.filterwarnings("ignore")

import pandas as pd

MA_REEKS = (50, 80, 100, 120, 140, 160, 180, 200, 250, 300)
KOSTEN_REEKS = (0.0005, 0.0010, 0.0025)
STANDAARD_KOSTEN = 0.0010


# ── data ──────────────────────────────────────────────────────────────────────
def reeks_yfinance():
    import yfinance as yf
    d = yf.Ticker("BTC-USD").history(period="max", auto_adjust=True)["Close"].dropna()
    d.index = d.index.tz_localize(None)
    return d


def reeks_binance():
    """Tweede bron. Gepagineerd, want één call geeft maximaal 1000 candles."""
    import ccxt
    ex = ccxt.binance({"enableRateLimit": True})
    sinds = ex.parse8601("2017-01-01T00:00:00Z")
    rijen = []
    while True:
        o = ex.fetch_ohlcv("BTC/USDT", "1d", since=sinds, limit=1000)
        if not o:
            break
        rijen += o
        if len(o) < 1000:
            break
        sinds = o[-1][0] + 86_400_000
    df = pd.DataFrame(rijen, columns=["t", "o", "h", "l", "c", "v"]).drop_duplicates("t")
    s = pd.Series(df["c"].values, index=pd.to_datetime(df["t"], unit="ms"))
    return s.sort_index()


# ── meten ─────────────────────────────────────────────────────────────────────
def draai(px, ma_bron, n, kosten=STANDAARD_KOSTEN, lag=1):
    """lag=1: handelen op de slotkoers die het signaal geeft (crypto handelt 24/7).
       lag=2: pas de dag erna — de strengere, realistischere variant."""
    sig = (ma_bron > ma_bron.rolling(n).mean()).astype(float)
    pos = sig.reindex(px.index).fillna(0).shift(lag).fillna(0)
    r = px.pct_change().fillna(0)
    wissels = pos.diff().abs().fillna(0)
    eq = (1 + (pos * r - wissels * kosten)).cumprod()
    return eq, int(wissels.sum())


def kentallen(eq):
    jaren = (eq.index[-1] - eq.index[0]).days / 365.25
    return (eq.iloc[-1] ** (1 / jaren) - 1) * 100, ((eq / eq.cummax()) - 1).min() * 100


def vasthouden(px):
    jaren = (px.index[-1] - px.index[0]).days / 365.25
    return ((px.iloc[-1] / px.iloc[0]) ** (1 / jaren) - 1) * 100, \
           ((px / px.cummax()) - 1).min() * 100


def tabel(px, ma_bron, titel, kosten=STANDAARD_KOSTEN, lag=1):
    bh_c, bh_dd = vasthouden(px)
    print("\n%s   (%s t/m %s)" % (titel, px.index[0].date(), px.index[-1].date()))
    print("   vasthouden: %+.1f%% CAGR, %.1f%% drawdown" % (bh_c, bh_dd))
    print("   %-5s %9s %9s %8s  %s" % ("MA", "CAGR", "max DD", "wissels", "beter?"))
    beter_c = beter_dd = 0
    for n in MA_REEKS:
        eq, w = draai(px, ma_bron, n, kosten, lag)
        c, dd = kentallen(eq)
        beter_c += c > bh_c
        beter_dd += dd > bh_dd
        merk = ("rendement " if c > bh_c else "") + ("drawdown" if dd > bh_dd else "")
        print("   %-5d %+8.1f%% %+8.1f%% %8d  %s" % (n, c, dd, w, merk or "—"))
    print("   -> %d/%d beter op rendement, %d/%d beter op drawdown"
          % (beter_c, len(MA_REEKS), beter_dd, len(MA_REEKS)))
    return beter_c, beter_dd


def main():
    y = reeks_yfinance()
    print("=" * 78)
    print("BTC-TRENDFILTER — in boven de MA, eruit eronder")
    print("=" * 78)
    print("Bron 1 (yfinance): %s t/m %s, %d dagen"
          % (y.index[0].date(), y.index[-1].date(), len(y)))

    tabel(y, y, "VOLLEDIG — bron yfinance")
    tabel(y[y.index >= "2021-01-01"], y, "OUT-OF-SAMPLE 2021-nu — bron yfinance")
    tabel(y[y.index >= "2024-01-01"], y, "HUIDIG REGIME 2024-nu — bron yfinance")

    print("\n" + "=" * 78)
    print("TOETS 1 — tweede databron")
    print("=" * 78)
    try:
        b = reeks_binance()
        print("Bron 2 (Binance BTC/USDT): %s t/m %s, %d dagen"
              % (b.index[0].date(), b.index[-1].date(), len(b)))
        tabel(b, b, "VOLLEDIG — bron Binance")
    except Exception as e:
        print("Binance ophalen mislukt: %s" % str(e)[:100])

    print("\n" + "=" * 78)
    print("TOETS 2 — uitvoeringsvertraging (2021-nu)")
    print("=" * 78)
    px = y[y.index >= "2021-01-01"]
    bh_c, bh_dd = vasthouden(px)
    print("vasthouden: %+.1f%% CAGR, %.1f%% DD" % (bh_c, bh_dd))
    print("   %-5s %-22s %-22s" % ("MA", "lag 1 (zelfde slot)", "lag 2 (dag later)"))
    for n in MA_REEKS:
        c1, d1 = kentallen(draai(px, y, n, lag=1)[0])
        c2, d2 = kentallen(draai(px, y, n, lag=2)[0])
        print("   %-5d %+9.1f%% / %+7.1f%%    %+9.1f%% / %+7.1f%%" % (n, c1, d1, c2, d2))

    print("\n" + "=" * 78)
    print("TOETS 3 — kostengevoeligheid (2021-nu, MA120)")
    print("=" * 78)
    for k in KOSTEN_REEKS:
        eq, w = draai(px, y, 120, kosten=k)
        c, dd = kentallen(eq)
        print("   %.2f%% per kant: %+7.1f%% CAGR, %+7.1f%% DD, %d wissels"
              % (k * 100, c, dd, w))

    print("\n" + "=" * 78)
    print("STAND VANDAAG")
    print("=" * 78)
    nu = y.iloc[-1]
    print("BTC $%.0f (%s)" % (nu, y.index[-1].date()))
    for n in (100, 120, 140, 200):
        ma = y.rolling(n).mean().iloc[-1]
        print("   MA%-4d $%8.0f  %+6.1f%%  %s"
              % (n, ma, (nu / ma - 1) * 100, "IN" if nu > ma else "ERUIT"))


if __name__ == "__main__":
    main()
