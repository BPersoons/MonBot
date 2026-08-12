"""Pre-flight: is het tranche-plan van de dip-koper uitvoerbaar bij dit budget?

    python -m tests.pre_flight.check_sleeve_sizing

## Waarom dit bestaat

Op 2026-08-12 bleek 79% van het sleeve-budget stil te staan ($201 van $255),
terwijl het INGEZETTE deel +22,4% deed. Niet de edge was klein, de inzet was
klein.

⚠️ **Deze check heeft de eerste verklaring daarvan meteen weerlegd**, en dat is
de reden hem te bewaren. Ik schreef eerst dat elke stap na T1 onder Hyperliquid's
$10-minimum viel. Bij 8 namen is dat waar ($6,38/stap), maar de sleeve stond op
4 namen — daar zijn de stappen $12,75/$19,13/$19,13/$12,75 en halen ze de vloer
allemaal. Het plan was rekenkundig gewoon uitvoerbaar. De echte oorzaak is een
andere:

  1. `t2_t4_enabled` staat niet in `thematic_exposure_state.json` → default
     False. Vervolgtranches hebben in het hele bestaan van de sleeve
     (sinds 2026-07-17) nooit gedraaid.
  2. Zelfs áán zou T2 niet vuren: de trigger vraagt -10% t.o.v. entry en de
     posities stonden +9% tot +29%. De 80% die voor T2-T4 gereserveerd stond,
     was geconditioneerd op ONGELIJK hebben.

Werkt de dip-buy-edge, dan komt dat geld dus nooit aan het werk. Dát is wat
deze check meet, en waarom scenario 5 een FAIL is en geen waarschuwing.

Het is bewust een **rekenkundige** test zonder netwerk: de conclusie hangt af
van drie constanten en één budget, allemaal lokaal bekend. Een test die de
exchange nodig heeft, draait niemand.

## De regel die deze check draagt

**Een stille skip is geen veilige skip, en een waarschuwing die PASS teruggeeft
is een stille skip in een andere jas.** `_open_tranche` heeft twee guards die een
order overslaan met alleen een INFO-log. Dat is het juiste gedrag op het moment
zelf, maar het maakt een structureel onuitvoerbaar plan onzichtbaar: het systeem
meldt nooit een fout en zet nooit geld aan het werk. Precies het faalpatroon
"gebouwd maar nooit gemeten" uit `.claude/commands/kritisch.md`.

## Hoe deze check zelf getest is

Tegen vijf configuraties, waarvan vier bekend fout: de oude stand van
2026-08-12, 8 namen op $255, een plan dat niet optelt tot 1,0, en een gat in de
stappen. Alle vier geven nu FAIL; de nieuwe stand geeft PASS. Bij een wijziging
hier: draai die scenario's opnieuw, anders test je alleen of hij "ja" kan zeggen.
"""

import sys

# Windows-console valt terug op cp1252 en breekt op elk niet-ASCII teken
# (zie CLAUDE.md, Windows compat). Deze check moet ook lokaal draaien.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Hyperliquid's minimum-notional plus de buffer die _open_tranche aanhoudt.
# Hardcoded, niet uit de exchange gelezen: deze check moet zonder netwerk
# draaien en $10 is een platformconstante, geen marktdata.
MIN_NOTIONAL_USD = 10.0
GUARD_BUFFER_USD = 1.0

# Het echte budget van de sleeve-wallet (gemeten op de keten 2026-08-12:
# xyz-dex accountValue $263,04). DEFAULT_BUDGET_USD is $1.250 en dus GEEN
# geldige testinvoer — juist het verschil tussen die twee veroorzaakte dit.
LIVE_BUDGET_USD = 255.0

# Hoeveel van het budget mag stilstaan als alleen T1 vuurt. De oude stand zat op
# 80% en dat is te veel: dat geld gaat pas werken als een positie 10% onder entry
# zakt. 65% laat een bewust voorzichtige 50/50-verdeling nog door en blokkeert de
# stand van 2026-08-12. Verhoog dit nooit om een check groen te krijgen — verhoog
# TRANCHE_PCTS[1], dat is waar het geld zit.
MAX_IDLE_PCT = 65.0


def _fmt(x):
    return f"${x:,.2f}"


def check_sleeve_sizing(budget_usd: float = LIVE_BUDGET_USD, verbose: bool = True) -> bool:
    from utils.thematic_exposure_lab import (MAX_CONCURRENT_NAMES, MAX_TRANCHE_STAGE,
                                             TRANCHE_PCTS)

    ok = True
    vloer = MIN_NOTIONAL_USD + GUARD_BUFFER_USD
    per_name = budget_usd / MAX_CONCURRENT_NAMES

    def zeg(s):
        if verbose:
            print(s)

    zeg(f"  budget {_fmt(budget_usd)} · {MAX_CONCURRENT_NAMES} namen | "
        f"per naam {_fmt(per_name)} | vloer {_fmt(vloer)}")

    # 1 — het plan moet optellen tot 1,0, anders belooft of verzwijgt het geld.
    som = sum(TRANCHE_PCTS.values())
    if abs(som - 1.0) > 1e-9:
        print(f"  FAIL  TRANCHE_PCTS telt op tot {som:.4f}, moet 1,0 zijn")
        ok = False
    else:
        zeg(f"  ok    tranche-plan telt op tot 1,0 ({len(TRANCHE_PCTS)} stappen)")

    # 2 — stappen moeten aaneengesloten bij 1 beginnen; _maybe_advance_tranches
    #     loopt met stage+1 en zou over een gat heen stappen.
    verwacht = list(range(1, len(TRANCHE_PCTS) + 1))
    if sorted(TRANCHE_PCTS) != verwacht:
        print(f"  FAIL  stappen {sorted(TRANCHE_PCTS)} zijn niet aaneengesloten {verwacht}")
        ok = False
    if MAX_TRANCHE_STAGE != max(verwacht):
        print(f"  FAIL  MAX_TRANCHE_STAGE={MAX_TRANCHE_STAGE} wijkt af van {max(verwacht)}")
        ok = False

    # 3 — de kern: haalt ELKE stap de min-notional-vloer? Zo niet, dan is dat
    #     deel van het budget structureel onbereikbaar en staat het stil.
    onbereikbaar = 0.0
    for stap in sorted(TRANCHE_PCTS):
        bedrag = per_name * TRANCHE_PCTS[stap]
        haalt = bedrag >= vloer
        if not haalt:
            onbereikbaar += bedrag * MAX_CONCURRENT_NAMES
            ok = False
        zeg(f"  {'ok   ' if haalt else 'FAIL '} T{stap} = {_fmt(bedrag)}/naam"
            f"{'' if haalt else '  <- onder de vloer, wordt STIL overgeslagen'}")
    if onbereikbaar:
        print(f"  FAIL  {_fmt(onbereikbaar)} van {_fmt(budget_usd)} "
              f"({onbereikbaar / budget_usd * 100:.0f}%) is onbereikbaar")

    # 4 — het plan mag het budget niet overschrijden.
    inzet = per_name * MAX_CONCURRENT_NAMES
    if inzet > budget_usd + 1e-6:
        print(f"  FAIL  volledig plan vraagt {_fmt(inzet)} > budget {_fmt(budget_usd)}")
        ok = False

    # 5 — de eigenlijke bevinding van 2026-08-12, en daarom een FAIL en geen
    #     waarschuwing. Vervolgtranches zijn geconditioneerd op VERLIES (-10%
    #     t.o.v. entry), dus "alleen T1 gevuld" is in een WERKENDE sleeve het
    #     normale scenario, niet het slechtste. Wat daar stil blijft staan, staat
    #     structureel stil. Een config die dat toestaat mag niet deployen.
    t1_totaal = per_name * TRANCHE_PCTS[1] * MAX_CONCURRENT_NAMES
    stil_pct = (budget_usd - t1_totaal) / budget_usd * 100
    zeg(f"  {'ok   ' if stil_pct <= MAX_IDLE_PCT else 'FAIL '} alleen T1 gevuld -> "
        f"{_fmt(t1_totaal)} ingezet, {stil_pct:.0f}% stil (max {MAX_IDLE_PCT:.0f}%)")
    if stil_pct > MAX_IDLE_PCT:
        print(f"  FAIL  {stil_pct:.0f}% van het budget staat stil zolang geen positie "
              f"10% onder entry zakt — geld dat alleen aan het werk gaat als we "
              f"ONGELIJK hebben. Verhoog TRANCHE_PCTS[1] of verlaag het budget.")
        ok = False

    return ok


def main() -> int:
    print("[check_sleeve_sizing] tranche-plan tegen het echte budget")
    goed = check_sleeve_sizing()

    # Tegenproef: dezelfde constanten bij het budget waarvoor het plan getekend
    # is. Slaagt die WEL en de live-check niet, dan is het probleem het budget
    # en niet het plan — dat verschil bepaalt de juiste ingreep.
    print("[check_sleeve_sizing] tegenproef op DEFAULT_BUDGET_USD")
    from utils.thematic_exposure_lab import DEFAULT_BUDGET_USD
    ontwerp = check_sleeve_sizing(DEFAULT_BUDGET_USD)
    if goed and not ontwerp:
        print("  info  plan past op het LIVE budget maar niet op het ontwerpbudget — "
              "bij een top-up moeten de tranches mee omhoog")

    print(f"[check_sleeve_sizing] {'PASS' if goed else 'FAIL'}")
    return 0 if goed else 1


if __name__ == "__main__":
    sys.exit(main())
