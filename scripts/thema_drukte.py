"""Drukte-meter: waar staat een thema in zijn cyclus?

    python scripts/thema_drukte.py

## De vraag

Ben-David e.a. (RFS 2023) laten zien dat thema-ETF's ~30% achterblijven in hun
eerste vijf jaar, omdat aanbieders lanceren wanneer een thema heet is. Dat maakt
de UITGIFTE van fondsen de zuiverste drukte-indicator die er is: een aanbieder
lanceert pas als hij denkt dat het verkoopt. De menigte is dus af te lezen aan
wanneer de fondsen zijn ontstaan, niet aan wat de koers doet.

Dit script leest per thema drie dingen af:

  1. WANNEER zijn de fondsen gelanceerd    -> is de menigte er al geweest?
  2. Hoe ver onder de eigen top staat het  -> zit het in de na-ijl of op de piek?
  3. Wat deed het tegen de wereldindex     -> was het uberhaupt de moeite waard?

## Hoe je dit leest

De combinatie telt, niet een los getal:

  veel VERSE lanceringen + dicht bij de top  -> de menigte zit er NU. Te laat.
  oude fondsen + diep onder de top          -> de menigte is vertrokken. Kan
                                               een kans zijn of een dood thema;
                                               dat beslist de keten-analyse.
  weinig fondsen + oud + dicht bij de top   -> zeldzaam: het werkt en niemand
                                               heeft er een product op gebouwd.

## De regel

**Een mislukte uitlezing telt NOOIT als nul.** Een fonds waarvan de koers niet
opgehaald kan worden verdwijnt uit de tabel met vermelding, niet als een 0%-regel
die het thema-gemiddelde omlaag trekt.

## Twee beperkingen die je moet kennen voordat je dit gebruikt

**1. De fondsenlijst hieronder is met de hand samengesteld en bestaat dus uit
OVERLEVERS.** Daardoor meet de uitgifte-indicator ("hoeveel gelanceerd in de
laatste 3 jaar") mijn selectie en niet de markt -- hij geeft bij elk thema 0,
want ik kende alleen de gevestigde namen. Voor een bruikbare uitgifte-meting is
een VOLLEDIGE lijst lanceringen per thema nodig (justETF's thema-paginas), incl.
de fondsen die inmiddels zijn opgeheven. Tot dat er is: lees kolom 2 en 3, niet
de uitgifte-regel.

**2. Het thema-label zegt niets over het mandje.** QTUM ("Defiance Quantum")
staat op +417pp tegenover de wereldindex, maar de top-10 bestaat uit Cloudflare,
Snowflake, RTX, NEC, Nutanix, Microsoft, Airbus en Amazon van elk ~1,4% -- echt
quantum is ~3,1%. Dat is een gelijkgewogen tech/industrie-mand met een etiket.
Die +417pp is dus geen quantum-these die uitkwam. Draai altijd
scripts/keten_overlap.py voordat je een getal uit deze tabel gelooft.

Let op: dit meet de VS-genoteerde fondsen. Die hebben de langste historie en de
beste datadekking. Voor de daadwerkelijke aankoop gebruik je de UCITS-variant --
zie scripts/keten_overlap.py voor de overlaptoets op de holdings.
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WERELD = "URTH"

THEMAS = {
    "AI":            ["AIQ", "IRBO", "ARTY", "THNQ"],
    "Robotics":      ["ROBO", "BOTZ", "ARKQ", "IRBO"],
    "Space":         ["UFO", "ARKX", "ROKT"],
    "Quantum":       ["QTUM"],
    "Cybersecurity": ["HACK", "CIBR", "BUG"],
    "Cloud/SaaS":    ["SKYY", "WCLD", "CLOU"],
    # IJkpunten: thema's waarvan we WETEN hoe het afliep. Zonder deze weet je
    # niet hoe "druk" eruitziet -- ze kalibreren de schaal.
    "Schone energie (ijkpunt)": ["ICLN", "TAN", "PBW"],
    "Cannabis (ijkpunt)":       ["MJ", "MSOS"],
}


def haal(ticker):
    import yfinance as yf
    h = yf.Ticker(ticker).history(period="max", auto_adjust=True)["Close"].dropna()
    if len(h) < 100:
        return None
    return h


def rendement(reeks, vanaf=None):
    r = reeks if vanaf is None else reeks[reeks.index >= vanaf]
    if len(r) < 20:
        return None
    return (r.iloc[-1] / r.iloc[0] - 1) * 100


def main():
    import pandas as pd
    print("DRUKTE-METER — waar staat elk thema in zijn cyclus?")
    print("Bron: VS-genoteerde thema-ETF's, volledige historie. Peildatum vandaag.")
    print("=" * 96)

    wereld = haal(WERELD)
    if wereld is None:
        print("FOUT: wereldindex niet op te halen — zonder ijkpunt is geen enkel getal te duiden.")
        return 1

    mislukt = []
    for thema, tickers in THEMAS.items():
        print("")
        print(thema)
        print("  %-7s %-11s %6s %9s %11s %11s" %
              ("fonds", "gelanceerd", "leeftd", "vs top", "sinds start", "vs wereld"))
        launches = []
        for t in tickers:
            reeks = haal(t)
            if reeks is None:
                mislukt.append("%s (%s)" % (t, thema))
                continue
            start = reeks.index[0]
            launches.append(start)
            jaren = (reeks.index[-1] - start).days / 365.25
            top = reeks.max()
            vs_top = (reeks.iloc[-1] / top - 1) * 100
            eigen = rendement(reeks)
            # wereldindex over exact hetzelfde venster
            w = wereld[wereld.index >= start]
            ref = rendement(w) if len(w) >= 20 else None
            rel = "" if ref is None else "%+10.1fpp" % (eigen - ref)
            print("  %-7s %-11s %5.1fj %+8.1f%% %+10.1f%% %s"
                  % (t, str(start.date()), jaren, vs_top, eigen, rel))

        if launches:
            recent = [l for l in launches if (pd.Timestamp.now(tz=l.tz) - l).days < 365 * 3]
            print("    -> %d fonds(en), nieuwste %s, %d gelanceerd in de laatste 3 jaar"
                  % (len(launches), max(launches).date(), len(recent)))

    if mislukt:
        print("")
        print("  NIET OPGEHAALD (buiten de tabel gehouden, niet als 0 geteld): %s"
              % ", ".join(mislukt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
