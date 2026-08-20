"""Ketenoverlap: hoeveel van een thema-ETF zit in de schakel die je hebt aangewezen?

    python scripts/keten_overlap.py

## Waarom dit bestaat

`docs/CONVICTION_BARBELL_PLAN.md` kiest thema's op tolhuisje: *"wie kan hier de
prijs bepalen, en waarom kan niemand daaromheen?"* Bij slot 1 bleek dat de
gekozen ETF die these maar half dekte — de tolhuisjes waren ~15% van het fonds,
terwijl commodity-geheugen en een worstelende fab samen 22% waren. Die
constatering was met de hand gedaan en stond alleen in proza.

Dit script maakt er een getal van. Je schrijft de keten uit met per schakel een
oordeel over de overstapkosten, je typt de holdings over, en het rekent uit welk
deel van het fonds in de schakels zit waar jouw these over gaat.

## Waarom de holdings met de hand gaan

Voor Europese UCITS-fondsen geeft geen enkele gratis bron de holdings
programmatisch. `research/screen.py` doet hetzelfde (zie de peildatum daar). Dat
is per kandidaat eenmalig ~10 minuten overtikken. Zet ALTIJD de peildatum erbij:
zonder die datum weet je over een half jaar niet meer of het cijfer nog klopt.

## Twee regels

**1. Onmeetbaar telt niet als nul, maar valt uit de noemer.** Een holding die ik
niet kan thuisbrengen (verkeerd gelezen naam, onbekend bedrijf) krijgt `None` en
verdwijnt uit teller EN noemer, met vermelding. Hem op "lage overstapkosten"
zetten zou de score kunstmatig verlagen; op "hoge" kunstmatig verhogen.

**2. Overlap met de kern is een KOSTENPOST, geen neutrale weging.** Een
thema-ETF van 0,60% die voor 10% uit Microsoft, Alphabet en Amazon bestaat,
verkoopt je tegen 0,60% wat je in je wereldindexfonds al voor 0,07% bezit. Dat
deel is geen thema-blootstelling maar duurder gemaakte kern.
"""

import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── De these: welke schakels van de software-keten hebben overstapkosten? ──
# Uit docs/CONVICTION_BARBELL_PLAN.md slot 3: tolhuisje = switching costs.
HOOG, MIDDEN, LAAG = "hoog", "midden", "laag"

SCHAKELS = {
    "systems_of_record": (HOOG,  "ERP/CRM/HR/ITSM — bedrijfsproces zit erin verweven"),
    "database":          (HOOG,  "datagravity: applicaties herschrijven + egress"),
    "identity":          (HOOG,  "verweven met elke andere applicatie"),
    "observability":     (MIDDEN,"historische data maakt het plakkerig"),
    "data_platform":     (MIDDEN,"backup/infra, deels vervangbaar"),
    "security":          (LAAG,  "rip-and-replace gebeurt continu, hevige concurrentie"),
    "devtools":          (LAAG,  "versnipperd, ontwikkelaars stappen makkelijk over"),
    "commodity_infra":   (LAAG,  "capaciteit verhuren, concurrentie op prijs"),
    "netwerk_hardware":  (LAAG,  "geen software"),
    "megacap_kern":      (LAAG,  "zit al in het wereldindexfonds"),
}

# ── Holdings, met de hand overgetikt van justETF, peildatum 2026-08-18 ──
FONDSEN = {
    "WCLD — WisdomTree Cloud Computing": {
        "isin": "IE00BJGWQN72", "ter": 0.40, "index": "BVP Nasdaq Emerging Cloud",
        "gelanceerd": "2019-09-03", "omvang_eur_mln": 291, "yf": "WCLD",
        "holdings": [
            ("JFrog",            3.21, "devtools"),
            ("DigitalOcean",     3.17, "commodity_infra"),
            ("Palo Alto Networks",3.01, "security"),
            ("Datadog",          2.90, "observability"),
            ("CrowdStrike",      2.58, "security"),
            ("Okta",             2.38, "identity"),
            ("Twilio",           2.37, "commodity_infra"),
            ("Tenable",          2.27, "security"),
            ("Rubrik",           2.06, "data_platform"),
            ("Snowflake",        1.97, "database"),
        ],
    },
    "CPQ — First Trust Cloud Computing": {
        "isin": "IE00BFD2H405", "ter": 0.60, "index": "ISE Cloud Computing",
        "gelanceerd": "2018-12-27", "omvang_eur_mln": 383, "yf": "SKYY",
        "holdings": [
            ("Arista Networks",  4.18, "netwerk_hardware"),
            ("DigitalOcean",     3.95, "commodity_infra"),
            ("(onleesbaar)",     3.88, None),
            ("Nutanix",          3.84, "data_platform"),
            ("IBM",              3.70, None),
            ("Alphabet",         3.68, "megacap_kern"),
            ("Amazon",           3.45, "megacap_kern"),
            ("MongoDB",          3.27, "database"),
            ("Microsoft",        3.25, "megacap_kern"),
            ("CoreWeave",        2.97, "commodity_infra"),
        ],
    },
}


def score(fonds):
    gemeten = onmeetbaar = 0.0
    per_niveau = {HOOG: 0.0, MIDDEN: 0.0, LAAG: 0.0}
    kern = 0.0
    for naam, gewicht, schakel in fonds["holdings"]:
        if schakel is None or schakel not in SCHAKELS:
            onmeetbaar += gewicht
            continue
        niveau = SCHAKELS[schakel][0]
        per_niveau[niveau] += gewicht
        gemeten += gewicht
        if schakel == "megacap_kern":
            kern += gewicht
    return gemeten, onmeetbaar, per_niveau, kern


def main():
    print("KETENOVERLAP — slot 3, software-infrastructuur")
    print("These: tolhuisje = overstapkosten. Hoog = systems of record, database, identity.")
    print("Holdings met de hand overgetikt van justETF, peildatum 2026-08-18 (top 10).")
    print("=" * 78)

    for naam, f in FONDSEN.items():
        gemeten, onmeetbaar, niv, kern = score(f)
        print("\n%s" % naam)
        print("  %s | index: %s | TER %.2f%% | gelanceerd %s | EUR %d mln"
              % (f["isin"], f["index"], f["ter"], f["gelanceerd"], f["omvang_eur_mln"]))
        print("  top-10 beslaat %.2f%% van het fonds (%.2f%% daarvan onmeetbaar)"
              % (gemeten + onmeetbaar, onmeetbaar))
        for n in (HOOG, MIDDEN, LAAG):
            deel = niv[n] / gemeten * 100 if gemeten else 0
            print("    %-7s %5.2f%% van het fonds  = %5.1f%% van het gemeten deel" % (n, niv[n], deel))
        print("    OVERLAPSCORE (hoog / gemeten): %5.1f%%" % (niv[HOOG] / gemeten * 100 if gemeten else 0))
        if kern:
            print("    ! %.2f%% is megacap die je in de kern al bezit — die koop je hier "
                  "tegen %.2f%% i.p.v. 0,07%%" % (kern, f["ter"]))
        if onmeetbaar:
            print("    ! %.2f%% niet thuis te brengen — buiten teller EN noemer gehouden" % onmeetbaar)

    net_analyse()

    drukte_toets()

    print("\n" + "=" * 78)
    print("Systems of record in geen van beide fondsen: geen SAP, Oracle, ServiceNow,")
    print("Salesforce, Workday of Intuit. Dat is geen toeval — 'Emerging Cloud' sluit")
    print("de gevestigde partijen per indexdefinitie uit. Precies de schakel met de")
    print("hoogste overstapkosten is dus per constructie afwezig.")



# ══ Tweede these: stroom en net (research/themes.json, kaart "Stroom en net") ══
# De kaart wees als tolhuisje aan: netapparatuur + EPC-capaciteit. Nutsbedrijven
# zijn daar expliciet de AFNEMER met gereguleerd rendement, niet de partij met
# prijszettingsmacht — die tellen dus NIET mee in de teller.
#
# Waarom deze meting bestaat: de 72,2% op de kaart is gemeten op de AMERIKAANSE
# GRID, en die kun je als Europese particulier niet kopen (PRIIPs). De UCITS-versie
# volgt de EXCLUSIONS-variant van dezelfde index — andere index, dus de score
# draagt niet over en moet opnieuw. Zie docs/FONDSKEUZE_METHODE.md.

SCHAKELS_NET = {
    "netapparatuur":       (HOOG,  "transformatoren, schakelmateriaal, kabel — meerjarige levertijden"),
    "aanleg_epc":          (HOOG,  "EPC-capaciteit; de bottleneck is vakmensen, niet vraag"),
    "netbeheer":           (LAAG,  "AFNEMER met gereguleerd rendement — geen prijszettingsmacht"),
    "opwekking":           (LAAG,  "commodity-stroom"),
    "gebouwautomatisering": (LAAG, "buiten de keten: HVAC/gebouwbeheer, niet het net"),
}

FONDSEN_NET = {
    "GRID UCITS — First Trust Nasdaq Clean Edge Smart Grid Infrastructure": {
        "isin": "IE000J80JTL1", "ter": 0.63,
        "index": "Nasdaq OMX Clean Edge Smart Grid Infrastructure EXCLUSIONS",
        "gelanceerd": "2022-04-21", "omvang_eur_mln": 2458, "yf": "GRID",
        # Holdings van justETF, peildatum 2026-06-30. 109 posities; top-10 = 57,79%.
        "holdings": [
            ("Johnson Controls",  8.72, "gebouwautomatisering"),
            ("Eaton",             8.51, "netapparatuur"),
            ("Schneider Electric",8.29, "netapparatuur"),
            ("ABB",               8.12, "netapparatuur"),
            ("Quanta Services",   8.09, "aanleg_epc"),
            ("National Grid",     4.11, "netbeheer"),
            ("Prysmian",          3.87, "netapparatuur"),
            ("nVent Electric",    3.21, "netapparatuur"),
            ("Hubbell",           2.92, "netapparatuur"),
            ("TERNA",             1.95, "netbeheer"),
        ],
    },
}


def net_analyse():
    print("")
    print("=" * 78)
    print("KETENOVERLAP — stroom en net, de KOOPBARE (UCITS) variant")
    print("These: tolhuisje = netapparatuur + EPC. Nutsbedrijven zijn de afnemer.")
    print("=" * 78)
    for naam, f in FONDSEN_NET.items():
        gemeten = onmeetbaar = 0.0
        per_niveau = {HOOG: 0.0, MIDDEN: 0.0, LAAG: 0.0}
        for _n, gewicht, schakel in f["holdings"]:
            if schakel is None or schakel not in SCHAKELS_NET:
                onmeetbaar += gewicht
                continue
            per_niveau[SCHAKELS_NET[schakel][0]] += gewicht
            gemeten += gewicht
        print("")
        print("%s" % naam)
        print("  %s | index: %s" % (f["isin"], f["index"]))
        print("  TER %.2f%% | gelanceerd %s | EUR %d mln" % (f["ter"], f["gelanceerd"], f["omvang_eur_mln"]))
        print("  top-10 beslaat %.2f%% van het fonds" % (gemeten + onmeetbaar))
        for n in (HOOG, LAAG):
            print("    %-7s %5.2f%% van het fonds" % (n, per_niveau[n]))
        score_pct = per_niveau[HOOG] / gemeten * 100 if gemeten else 0
        print("    OVERLAPSCORE (tolhuisje / gemeten): %5.1f%%" % score_pct)
        print("")
        print("    Ter vergelijking, de kaart mat op de AMERIKAANSE GRID:")
        print("      42,25 van 58,54 procentpunt = 72,2%")
        print("      hier:  %.2f van %.2f procentpunt = %.1f%%" % (per_niveau[HOOG], gemeten + onmeetbaar, score_pct))
        buiten_keten = sum(g for _n, g, sch in f["holdings"] if sch == "gebouwautomatisering")
        print("")
        print("    Conservatief gerekend: Johnson Controls (%.2f%% — gebouwbeheer/HVAC) valt" % buiten_keten)
        print("    buiten de keten, maar blijft in de NOEMER: het is fondsgewicht dat je these")
        print("    niet uitdrukt, en dat is een kostenpost, geen neutrale weging (regel 2).")
        print("    Alleen hem uit de noemer halen zou %.1f%% geven — dat vleit."
              % (per_niveau[HOOG] / (gemeten - buiten_keten) * 100 if gemeten > buiten_keten else 0))
        print("    De nutsbedrijven (National Grid, TERNA, %.2f%%) blijven er sowieso in:"
              % (per_niveau[LAAG] - buiten_keten))
        print("    die zitten WEL in de keten, alleen niet in de schakel met de macht.")

def drukte_toets():
    """Wat DEED het thema? Beide fondsen bestaan lang genoeg voor een uitslag.

    De leeftijdstoets (is de index ouder dan het thema?) is een proxy voor "was
    de menigte er al". Bij deze twee hoeft die proxy niet: er is zeven jaar live
    data, dus we meten het gewoon. Let op het breekpunt van november 2021 -- daar
    kantelt de hele reeks, en dat is precies het patroon uit Ben-David e.a.: het
    rendement zit VOOR de instroom, niet erna.
    """
    try:
        import yfinance as yf
    except Exception as e:
        print("  (drukte-toets overgeslagen: %s)" % e)
        return

    def reeks(t, start):
        return yf.Ticker(t).history(start=start, auto_adjust=True)["Close"].dropna()

    def rend(x, a, b):
        x = x[(x.index.strftime("%Y-%m-%d") >= a) & (x.index.strftime("%Y-%m-%d") <= b)]
        return None if len(x) < 20 else (x.iloc[-1] / x.iloc[0] - 1) * 100

    print("")
    print("=" * 78)
    print("DRUKTE-TOETS -- wat deed het thema echt?")
    print("(US-genoteerde zusterfondsen op dezelfde index, langere historie)")
    try:
        r = {"SKYY (= CPQ)": reeks("SKYY", "2011-01-01"),
             "WCLD": reeks("WCLD", "2019-09-01"),
             "URTH (wereld)": reeks("URTH", "2012-01-01")}
    except Exception as e:
        print("  (koersen ophalen mislukt: %s)" % e)
        return

    for a, b, label in [("2019-09-06", "2026-08-15", "sinds WCLD-lancering (7 jaar)"),
                        ("2019-09-06", "2021-11-15", "aanloop naar de piek van nov 2021"),
                        ("2021-11-15", "2026-08-15", "sinds die piek")]:
        basis = rend(r["URTH (wereld)"], a, b)
        print("")
        print("  %s" % label)
        for naam, x in r.items():
            v = rend(x, a, b)
            if v is None:
                continue
            extra = "" if naam.startswith("URTH") or basis is None else "  (%+.1fpp t.o.v. wereld)" % (v - basis)
            print("    %-16s %+8.1f%%%s" % (naam, v, extra))


if __name__ == "__main__":
    main()
