"""Laag-1 screen: welke namen zakken NIEUW onder hun 200-daags gemiddelde?

    python research/screen.py           # volledig verslag
    python research/screen.py --nieuw   # alleen namen die nog niet in de ledger staan

De trechter. `track.py` bewaakt wat er al in zit; dit vult hem aan.

Volgorde van de filters is die van research/README.md — poorten eerst, dan pas
de divergentie-vraag:

  1. koers NU onder de 200d-MA      <- de BLKB-les: 52wk vindt, de MA bepaalt of
                                       de daling er nog IS. BLKB stond -28% over
                                       52 weken en +42% boven zijn 50d-MA: het
                                       herstel was al voorbij.
  2. marktkap $300M - $50 mrd       <- liquiditeit + geen kern-ETF-overlap
  3. winstgevend                    <- overlevingspoort
  4. omzetgroei >= 0                <- fundamentals zakten niet mee

Een treffer is een KANDIDAAT, geen bevinding. De kaart doet het werk: AMSC kwam
hier als treffer uit en werd op de kaart alsnog AFVALLER (dalende brutomarges),
en bij CHRW gaf het `revenueGrowth`-veld +19,3% terwijl de brutowinst 14% daalde.
Daarom staat er in laag 1 nooit een verdict.
"""

import io
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

HERE = os.path.dirname(os.path.abspath(__file__))
UITVOER = os.path.join(HERE, "screen_result.json")

MIN_CAP, MAX_CAP = 300e6, 50e9

# Universum uit de holdings van thema-ETF's (peildatum 2026-08-07/10). Gekozen om
# sectoren te spreiden: net, cyber, cloud, banken, transport, pharma, voeding,
# schone energie. Uitbreiden = hier een regel toevoegen.
UNIVERSUM = {
    "GRID (netinfrastructuur)":
        "ETN JCI PWR NVT HUBB ITRI ATKR MYRG ENPH AMSC WLDN PLPC MTZ WCC GNRC TRMB "
        "AEIS LFUS AES VMI ESE ACA ENS AZZ BDC DGII PRIM",
    "CIBR (cybersecurity)":
        "PANW CRWD FTNT OKTA ZS FFIV RBRK GEN DT FROG LDOS CHKP BAH S TENB NTCT ATEN "
        "ZD RDWR CVLT VRNS",
    "SKYY (cloud)":
        "NTNX ANET MDB NET DOCN TEAM SHOP TWLO GTLB HPE FSLY WK RNG NTAP DELL AKAM "
        "HUBS LUMN FIVN WIX QLYS PAYC APPN BLKB QTWO TOST VEEV PCTY DBX BOX APPF DOCU "
        "ESTC KVYO OTEX ZM ASAN BL FIG TTD",
    "FTXO (banken)":
        "BAC C JPM WFC TFC PNC USB CFG MTB FCNCA FITB HBAN RF KEY EWBC WBS SSB ONB "
        "UMBF FHN ZION VLY BPOP PB FNB WTFC WAL BOKF OZK UBSI ASB CFR HWC HOMB ABCB "
        "CBSH FBP CATY WSFS PRK FFBC FULT FIBK AX NIC IBOC TRMK SFBS TCBI BKU",
    "FTXR (transport)":
        "GM UNP F UPS TSLA DAL URI CSX UAL AAL PCAR R FDX BWA WAB JBHT LUV ODFL KNX "
        "EXPD GPC SKYW LEA XPO ALSN LKQ CHRW OSK KEX MATX GATX GTX GNTX SAIA INSW "
        "DORM FSS LSTR PHIN DAN ATMU GXO FTAI",
    "FTXH (pharma)":
        "LLY ABBV MRK JNJ BMY VTRS BIIB AMGN VRTX CAH REGN PFE GILD UTHR JAZZ INCY "
        "ILMN ZTS CRL EXEL MEDP HALO BMRN NBIX ALKS PTCT TWST TXG SYRE TVTX GH PTGX "
        "TGTX ELAN AMRX ARWR LGND RCUS ROIV ACAD KRYS KYMR MRNA MIRM ARQT TARS SUPN "
        "IONS ALNY",
    "FTXG (voeding)":
        "ADM KO KHC MDLZ PEP MNST KDP USFD CTVA TSN STZ CALM GIS HSY SJM CPB COKE "
        "INGR HRL BF-B BG MKC POST SEB DAR COCO CELH FIZZ FRPT",
    "QCLN (schone energie)":
        "MPWR FSLR BE ON RIVN AEIS ALB AYI BEP MP NXT ALGM VICR ORA ENS ENPH HASI "
        "OLED CWEN SQM NVTS POWI PLUG LCID RUN SEDG AMPX FLNC FCEL SHLS WOLF EOSE "
        "SGML WLDN ENVX AMRC LYTS ARRY BLDP ASPN GEVO CLNE EVGO MNTK",
}


def bekende_tickers():
    """Alles wat al in de ledger staat — inclusief afvallers.

    Een AFVALLER hoort niet opnieuw als 'nieuwe kandidaat' op te duiken; die
    wordt bewaakt via zijn terugkeervoorwaarde in track.py fundamentals.
    """
    with io.open(os.path.join(HERE, "ledger.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    return {e["ticker"] for e in d["entries"]}


def screen(alleen_nieuw=False):
    import yfinance as yf

    naar_thema = {}
    for thema, namen in UNIVERSUM.items():
        for t in namen.split():
            naar_thema.setdefault(t, thema)
    alle = sorted(naar_thema)
    bekend = bekende_tickers()

    print("Universum: %d namen over %d thema's" % (len(alle), len(UNIVERSUM)))
    print("Al in de ledger: %d\n" % len(bekend))

    print("Stap 1 — koers versus 200-daags gemiddelde...")
    data = yf.download(alle, period="1y", progress=False, auto_adjust=True)["Close"]
    onder = []
    for t in alle:
        if t not in data.columns:
            continue
        s = data[t].dropna()
        if len(s) < 200:
            continue
        px = float(s.iloc[-1])
        ma200 = float(s.rolling(200).mean().iloc[-1])
        if px < ma200:
            onder.append({
                "ticker": t, "thema": naar_thema[t], "koers": round(px, 2),
                "vs_200d_pct": round((px / ma200 - 1) * 100, 1),
                "vs_50d_pct": round((px / float(s.rolling(50).mean().iloc[-1]) - 1) * 100, 1),
                "chg_52w_pct": round((px / float(s.iloc[0]) - 1) * 100, 1),
                "in_ledger": t in bekend,
            })
    print("  %d van %d onder de 200d-MA (%.0f%%)\n"
          % (len(onder), len(alle), 100.0 * len(onder) / max(len(alle), 1)))

    kandidaten = [r for r in onder if not r["in_ledger"]] if alleen_nieuw else onder
    print("Stap 2 — poorten en fundamentals voor %d namen...\n" % len(kandidaten))

    treffers, afgevallen = [], []
    for r in kandidaten:
        try:
            info = yf.Ticker(r["ticker"]).info
        except Exception:
            continue
        mc = info.get("marketCap") or 0
        if not (MIN_CAP <= mc <= MAX_CAP):
            continue
        pm, ocf = info.get("profitMargins"), info.get("operatingCashflow")
        if not ((pm is not None and pm > 0) or (ocf is not None and ocf > 0)):
            continue
        rg = info.get("revenueGrowth")
        r.update({
            "naam": (info.get("shortName") or "")[:28],
            "mktcap_mrd": round(mc / 1e9, 2),
            "pe": info.get("trailingPE"),
            "fwd_pe": info.get("forwardPE"),
            "omzetgroei_pct": round(rg * 100, 1) if rg is not None else None,
            "brutomarge_pct": round((info.get("grossMargins") or 0) * 100, 1),
        })
        (treffers if (rg is not None and rg >= 0) else afgevallen).append(r)

    treffers.sort(key=lambda r: r["vs_200d_pct"])
    nieuw = [r for r in treffers if not r["in_ledger"]]

    print("=" * 96)
    print("TREFFERS — onder de 200d-MA, winstgevend, omzet niet gedaald")
    print("=" * 96)
    print("%-6s %-28s %8s %8s %8s %8s  %s" %
          ("", "naam", "mktcap", "vs200", "omzet+", "PE", "status"))
    print("-" * 96)
    for r in treffers:
        print("%-6s %-28s %7.1fB %+7.1f%% %+7.1f%% %8s  %s" % (
            r["ticker"], r["naam"], r["mktcap_mrd"], r["vs_200d_pct"],
            r["omzetgroei_pct"], ("%.1f" % r["pe"]) if r["pe"] else "n/a",
            "in ledger" if r["in_ledger"] else "** NIEUW **"))

    if afgevallen:
        print("\nAfgevallen op dalende omzet (divergentie-screen rij 4): %s"
              % ", ".join(r["ticker"] for r in afgevallen))

    print("\n%d treffers, waarvan %d nieuw." % (len(treffers), len(nieuw)))
    if nieuw:
        print("Volgende stap:  /scorecard %s" % nieuw[0]["ticker"])
    print("\nLet op: een treffer is een KANDIDAAT, geen bevinding. AMSC kwam hier ook")
    print("uit en werd op de kaart alsnog AFVALLER wegens dalende brutomarges.")

    with io.open(UITVOER, "w", encoding="utf-8") as fh:
        json.dump({"universum": len(alle), "onder_200d": len(onder),
                   "treffers": treffers, "nieuw": [r["ticker"] for r in nieuw]},
                  fh, indent=2, ensure_ascii=False)

    if os.environ.get("GITHUB_OUTPUT") and nieuw:
        regels = ["<b>Scorekaart — nieuwe kandidaten</b>", ""]
        for r in nieuw[:8]:
            regels.append("• <b>%s</b> (%s) %s — %+.1f%% t.o.v. 200d-MA, omzet %+.1f%%, PE %s"
                          % (r["ticker"], r["thema"].split()[0], r["naam"],
                             r["vs_200d_pct"], r["omzetgroei_pct"],
                             ("%.1f" % r["pe"]) if r["pe"] else "n/a"))
        regels.append("\nKandidaten, geen bevindingen — <code>/scorecard &lt;TICKER&gt;</code>")
        with io.open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("nieuw=true\n")
            fh.write("message<<SCREEN_EOF\n%s\nSCREEN_EOF\n" % "\n".join(regels))
    elif os.environ.get("GITHUB_OUTPUT"):
        with io.open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("nieuw=false\nmessage<<SCREEN_EOF\n\nSCREEN_EOF\n")

    return treffers


if __name__ == "__main__":
    screen(alleen_nieuw="--nieuw" in sys.argv)
