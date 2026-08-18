"""Houdt de regel stand? "Het oudere fonds verslaat het nieuwere, binnen hetzelfde thema."

    python scripts/fondsregel_toets.py

## Waarom

Op 2026-08-18 kwam die regel drie keer onafhankelijk boven (robotics 426pp, cloud
129pp, space 57pp — zie docs/FONDSKEUZE_METHODE.md). Drie gevallen zijn een
patroon, geen bewijs. Dit script toetst hem over alle thema's die we kunnen
ophalen, zodat er een uitslag ligt VOORDAT er geld in gaat.

Twee uitkomsten, allebei bruikbaar:
  - regel houdt stand  -> een verdedigbare selectiemethode zonder een euro te wagen
  - regel valt om      -> dan zagen we drie toevalligheden en is de hele
                          thema-satelliet een slecht idee. Ook winst, en veel
                          goedkoper dan er kapitaal in stoppen.

## De opzet: paarsgewijs, over het GEMEENSCHAPPELIJKE venster

Per thema vergelijk ik elk paar fondsen (ouder, nieuwer) vanaf de dag dat de
JONGSTE van de twee bestond. Anders vergelijk je verschillende tijdvakken en meet
je de markt in plaats van de fondsen -- precies de definitiefout waar dit project
vaker in is getrapt.

## Waarom deze toets CONSERVATIEF is voor de eigen hypothese

Opgeheven fondsen staan niet meer in de data. Fondsen die worden opgeheven zijn
meestal de mislukkingen, en jonge thema-fondsen sneuvelen vaker dan oude. De
overlevingsbias werkt dus **in het voordeel van de jongere fondsen** -- tegen de
hypothese in. Houdt de regel ondanks die bias stand, dan is dat een sterker
resultaat dan het cijfer suggereert.

## De regel die dit script draagt

**Een mislukte uitlezing telt NOOIT als nul.** Een fonds zonder bruikbare reeks
verdwijnt uit alle paren, met vermelding -- niet als een 0%-regel die het
gemiddelde vervuilt.
"""

import sys
from itertools import combinations

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WERELD = "URTH"

# US-genoteerde thema-ETF's: langste historie en beste datadekking.
THEMAS = {
    "AI":               ["AIQ", "IRBO", "ARTY", "THNQ"],
    "Robotics":         ["ROBO", "BOTZ", "ARKQ", "IRBO"],
    "Space":            ["ROKT", "UFO", "ARKX", "NASA"],
    "Cybersecurity":    ["HACK", "CIBR", "BUG", "IHAK"],
    "Cloud/SaaS":       ["SKYY", "CLOU", "WCLD"],
    "Halfgeleiders":    ["SMH", "SOXX", "XSD", "PSI"],
    "Schone energie":   ["ICLN", "PBW", "QCLN", "TAN"],
    "Genomica":         ["ARKG", "IDNA", "GNOM"],
    "Fintech":          ["FINX", "ARKF", "IPAY", "TPAY"],
    "Cannabis":         ["MJ", "MSOS", "YOLO"],
    "Infrastructuur":   ["PAVE", "IFRA", "IGF"],
    "Water":            ["PHO", "FIW", "CGW", "PIO"],
    "Luchtvaart/defensie": ["ITA", "PPA", "XAR"],
    "Gaming/esports":   ["ESPO", "HERO", "NERD"],
    "Blockchain":       ["BLOK", "BLCN", "LEGR"],
    "Batterij/EV":      ["LIT", "DRIV", "IDRV", "BATT"],
    "Grondstoffen-mijnbouw": ["XME", "PICK", "REMX"],
    "Biotech":          ["XBI", "IBB", "ARKG"],
    "Nucleair/uranium": ["URA", "NLR", "URNM"],
    "Vergrijzing/zorg": ["XLV", "IHI", "IHF"],
}


def haal(ticker, cache={}):
    if ticker in cache:
        return cache[ticker]
    import yfinance as yf
    try:
        h = yf.Ticker(ticker).history(period="max", auto_adjust=True)["Close"].dropna()
        cache[ticker] = h if len(h) >= 250 else None
    except Exception:
        cache[ticker] = None
    return cache[ticker]


def rend_vanaf(reeks, start):
    x = reeks[reeks.index >= start]
    return None if len(x) < 60 else (x.iloc[-1] / x.iloc[0] - 1) * 100


def main():
    print("FONDSREGEL-TOETS — verslaat het OUDERE fonds het nieuwere, binnen hetzelfde thema?")
    print("Paarsgewijs, elk paar gemeten vanaf de lancering van de JONGSTE van de twee.")
    print("=" * 92)

    wereld = haal(WERELD)
    if wereld is None:
        print("FOUT: wereldindex niet op te halen — zonder ijkpunt geen duiding.")
        return 1

    paren, ontbreekt = [], []
    for thema, tickers in THEMAS.items():
        reeksen = {}
        for t in tickers:
            r = haal(t)
            if r is None:
                ontbreekt.append("%s (%s)" % (t, thema))
            else:
                reeksen[t] = r
        for a, b in combinations(sorted(reeksen, key=lambda x: reeksen[x].index[0]), 2):
            ra, rb = reeksen[a], reeksen[b]
            start = max(ra.index[0], rb.index[0])
            va, vb = rend_vanaf(ra, start), rend_vanaf(rb, start)
            if va is None or vb is None:
                continue
            paren.append({"thema": thema, "oud": a, "nieuw": b,
                          "start": start.date(), "oud_pct": va, "nieuw_pct": vb,
                          "marge": va - vb,
                          "jaren_verschil": (rb.index[0] - ra.index[0]).days / 365.25})

    if not paren:
        print("Geen bruikbare paren.")
        return 1

    gewonnen = [p for p in paren if p["marge"] > 0]
    marges = sorted(p["marge"] for p in paren)
    mediaan = marges[len(marges) // 2]

    print("")
    print("  paren getoetst        : %d, over %d thema's" % (len(paren), len(set(p["thema"] for p in paren))))
    print("  oudere fonds wint     : %d van %d = %.0f%%" % (len(gewonnen), len(paren), len(gewonnen) / len(paren) * 100))
    print("  mediane marge         : %+.1fpp ten gunste van het oudere fonds" % mediaan)
    print("  gemiddelde marge      : %+.1fpp" % (sum(p["marge"] for p in paren) / len(paren)))
    print("")
    print("  Munt opgooien zou 50%% geven. Alles daarboven is het signaal.")

    print("")
    print("  Grootste marges VOOR de regel:")
    for p in sorted(paren, key=lambda x: -x["marge"])[:6]:
        print("    %-22s %-6s (oud) vs %-6s  vanaf %s  %+8.1fpp"
              % (p["thema"], p["oud"], p["nieuw"], p["start"], p["marge"]))
    print("")
    print("  Grootste marges TEGEN de regel:")
    for p in sorted(paren, key=lambda x: x["marge"])[:6]:
        print("    %-22s %-6s (oud) vs %-6s  vanaf %s  %+8.1fpp"
              % (p["thema"], p["oud"], p["nieuw"], p["start"], p["marge"]))

    per_thema = {}
    for p in paren:
        per_thema.setdefault(p["thema"], []).append(p["marge"] > 0)
    print("")
    print("  Per thema (aandeel paren waarin het oudere fonds wint):")
    for thema in sorted(per_thema, key=lambda t: -sum(per_thema[t]) / len(per_thema[t])):
        v = per_thema[thema]
        print("    %-24s %d/%d" % (thema, sum(v), len(v)))

    if ontbreekt:
        print("")
        print("  NIET OPGEHAALD (buiten alle paren gehouden, niet als 0 geteld):")
        print("    %s" % ", ".join(ontbreekt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
