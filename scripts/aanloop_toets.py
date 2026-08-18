"""Voorspelt de AANLOOP van een thema hoe een nieuw fonds het daarna doet?

    python scripts/aanloop_toets.py

## De vraag

De eerste toets (`fondsregel_toets.py`) verwierp "het oudere fonds wint". Wat
overeind bleef is het mechanisme uit Ben-David e.a. (RFS 2023): fondsen worden
gelanceerd wanneer een thema heet is, dus je koopt de onderliggende bedrijven op
een hoge waardering.

Dat is **vooruit af te lezen**, en dat is het hele punt. Op de dag van lancering
kun je zien wat het thema de twee jaar daarvoor deed. Je hebt geen glazen bol
nodig -- alleen de grafiek tot dat moment.

    aanloop  = rendement van het thema in de 24 maanden VOOR de lancering
               (gemeten aan het oudste fonds in dat thema, als proxy)
    uitkomst = rendement van het nieuwe fonds over een VASTE periode na de
               lancering (36 maanden), MINUS de wereldindex over datzelfde venster

Hypothese: hoe harder de aanloop, hoe slechter de uitkomst.

## Wat de uitslagen betekenen

  duidelijk negatief verband -> een bruikbare, vooruit toepasbare regel:
                                koop geen fonds dat na een grote run lanceert
  geen verband                -> ook het mechanisme is hier niet meetbaar, en
                                dan blijft alleen de mandanalyse over

## Twee methodische keuzes, expliciet

**1. Het oudste fonds als thema-proxy.** Niet perfect -- dat fonds is zelf een
mand -- maar het is de enige reeks die vóór de lancering al bestond. Zonder
proxy is er geen aanloop te meten.

**2. Uitkomst is RELATIEF aan de wereldindex.** Absoluut rendement zou vooral de
markt meten. Een fonds dat +40% deed terwijl de wereld +60% deed, heeft verloren.

**3. VASTE periode van 36 maanden na lancering, niet "tot nu".** De eerste versie
van dit script mat het rendement sinds lancering, en dat is een definitiefout: XSD
(2006) had dan twintig jaar samengestelde groei en MSOS (2020) zes. Die +1726pp
mat horizon, geen kwaliteit. Met een vaste periode is elke waarneming
vergelijkbaar. Fondsen jonger dan 36 maanden vallen daardoor buiten de steekproef
-- terecht, want van die uitkomst weten we nog niets.

## De regel

**Een mislukte uitlezing telt NOOIT als nul.** Een fonds zonder bruikbare reeks,
of een thema waarvan het oudste fonds geen 24 maanden voorgeschiedenis heeft,
valt uit de steekproef met vermelding -- niet als een 0-waarneming.
"""

import sys
from datetime import timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WERELD = "URTH"
AANLOOP_MND = 24
HORIZON_MND  = 36           # vaste meetperiode na lancering; maakt waarnemingen vergelijkbaar
MIN_DAGEN_NA = int(HORIZON_MND * 30.44)

from fondsregel_toets import THEMAS, haal          # hergebruik, geen tweede lijst


def rend(reeks, van=None, tot=None):
    x = reeks
    if van is not None:
        x = x[x.index >= van]
    if tot is not None:
        x = x[x.index <= tot]
    return None if len(x) < 40 else (x.iloc[-1] / x.iloc[0] - 1) * 100


def main():
    print("AANLOOP-TOETS — voorspelt de run VOOR een lancering de uitkomst erna?")
    print("Uitkomst = eerste %d maanden na lancering, relatief aan de wereldindex." % HORIZON_MND)
    print("=" * 90)

    wereld = haal(WERELD)
    if wereld is None:
        print("FOUT: wereldindex niet op te halen.")
        return 1

    waarnemingen, overgeslagen = [], []
    for thema, tickers in THEMAS.items():
        reeksen = {t: haal(t) for t in tickers}
        reeksen = {t: r for t, r in reeksen.items() if r is not None}
        if len(reeksen) < 2:
            overgeslagen.append("%s (te weinig fondsen met data)" % thema)
            continue
        oudste = min(reeksen, key=lambda t: reeksen[t].index[0])
        proxy = reeksen[oudste]

        for t, r in reeksen.items():
            if t == oudste:
                continue
            start = r.index[0]
            if (r.index[-1] - start).days < MIN_DAGEN_NA:
                overgeslagen.append("%s (%s): te kort na lancering" % (t, thema))
                continue
            venster_start = start - timedelta(days=AANLOOP_MND * 30)
            if proxy.index[0] > venster_start:
                overgeslagen.append("%s (%s): thema-proxy heeft geen %d mnd aanloop"
                                    % (t, thema, AANLOOP_MND))
                continue
            aanloop = rend(proxy, venster_start, start)
            eind = start + timedelta(days=int(HORIZON_MND * 30.44))
            uit_fonds = rend(r, start, eind)
            uit_wereld = rend(wereld, start, eind)
            if aanloop is None or uit_fonds is None or uit_wereld is None:
                overgeslagen.append("%s (%s): onvoldoende data" % (t, thema))
                continue
            waarnemingen.append({"thema": thema, "fonds": t, "proxy": oudste,
                                 "start": start.date(), "aanloop": aanloop,
                                 "relatief": uit_fonds - uit_wereld})

    if len(waarnemingen) < 8:
        print("Te weinig waarnemingen (%d) voor een uitspraak." % len(waarnemingen))
        return 1

    n = len(waarnemingen)
    xs = [w["aanloop"] for w in waarnemingen]
    ys = [w["relatief"] for w in waarnemingen]
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    r = sxy / (sxx * syy) ** 0.5 if sxx and syy else 0.0

    print("")
    print("  waarnemingen        : %d fondsen over %d thema's" % (n, len(set(w["thema"] for w in waarnemingen))))
    print("  correlatie aanloop <-> latere relatieve prestatie: %+.2f" % r)
    if n > 3:
        t_stat = r * ((n - 2) / (1 - r ** 2)) ** 0.5 if abs(r) < 1 else 0
        print("  t-waarde            : %+.2f   (onder ~2 kun je toeval niet uitsluiten)" % t_stat)

    helft = sorted(waarnemingen, key=lambda w: w["aanloop"])
    laag, hoog = helft[: n // 2], helft[-(n // 2):]
    gl = sum(w["relatief"] for w in laag) / len(laag)
    gh = sum(w["relatief"] for w in hoog) / len(hoog)
    print("")
    print("  RUSTIGE aanloop (laagste helft, gem. %+.0f%%): daarna gemiddeld %+.1fpp t.o.v. wereld" % (sum(w["aanloop"] for w in laag)/len(laag), gl))
    print("  HETE   aanloop (hoogste helft, gem. %+.0f%%): daarna gemiddeld %+.1fpp t.o.v. wereld" % (sum(w["aanloop"] for w in hoog)/len(hoog), gh))
    print("  verschil: %+.1fpp in het %s van de rustige aanloop" % (gl - gh, "voordeel" if gl > gh else "nadeel"))

    print("")
    print("  Heetste aanlopen (en wat er daarna gebeurde):")
    for w in sorted(waarnemingen, key=lambda x: -x["aanloop"])[:8]:
        print("    %-20s %-6s lancering %s  aanloop %+7.0f%%  daarna %+8.1fpp"
              % (w["thema"], w["fonds"], w["start"], w["aanloop"], w["relatief"]))
    print("")
    print("  Rustigste aanlopen:")
    for w in sorted(waarnemingen, key=lambda x: x["aanloop"])[:8]:
        print("    %-20s %-6s lancering %s  aanloop %+7.0f%%  daarna %+8.1fpp"
              % (w["thema"], w["fonds"], w["start"], w["aanloop"], w["relatief"]))

    if overgeslagen:
        print("")
        print("  BUITEN DE STEEKPROEF (niet als 0 geteld): %d" % len(overgeslagen))
        for o in overgeslagen[:10]:
            print("    %s" % o)
    return 0


if __name__ == "__main__":
    sys.exit(main())
