"""Verslaat de dip-koper de wereldindex, of lift hij mee?

    python scripts/sleeve_benchmark.py [--file <positiebestand>] [--index URTH]

## De vraag

De dip-koper stond op 2026-08-12 op +22,4% over het ingezette kapitaal. Dat
getal zegt op zichzelf niets: als de markt in dezelfde weken +20% deed, is het
resultaat de markt en niet de strategie. Dit script legt naast elke positie wat
dezelfde dollars op dezelfde dag in de wereldindex hadden gedaan.

Dat is precies de vraag die de poort in `docs/PLAN_2026-08.md` stelt — "versla
de wereld-ETF over dezelfde periode" — en die tot nu toe alleen aan de PAPIEREN
analyse werd gesteld. `research/ledger.json` heeft een benchmarkkoers op elke
regel; het potje met echt geld erin had er geen enkele. Dit sluit dat gat.

## Waarom URTH

Dezelfde index als de scorekaart gebruikt. Eén meetlat over beide lijnen, zodat
"onze selectie" en "onze dip-koper" tegen hetzelfde worden afgezet en onderling
vergelijkbaar zijn. Overschrijfbaar met --index, maar doe dat alleen met reden.

## Twee regels die dit script draagt

**1. Een mislukte uitlezing telt NOOIT als 0.** Zonder indexkoers op de
aankoopdag is er geen vergelijking; die positie krijgt `onbekend` en valt buiten
het totaal, met vermelding. Anders zou een netwerkfout stil als "de index deed
niets" doorwerken en de uitkomst in ons voordeel kleuren.

**2. Gesloten posities zijn (nog) niet te beoordelen.** Bij een close gaan
`quantity` en `cost_basis_usd` naar 0; het resultaat verdween in één somveld.
Sinds 2026-08-12 houdt de sleeve `realized_pnl_usd` en `entry_cost_basis_usd`
per positie bij, maar de vier posities van vóór die datum zijn niet meer te
reconstrueren. Ze worden geteld en benoemd, niet weggelaten en niet geraden.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

STANDAARD_BESTAND = "thematic_exposure_positions.json"
STANDAARD_INDEX = "URTH"


def _lees_posities(pad):
    with open(pad, encoding="utf-8") as fh:
        return json.load(fh)


def _index_reeks(symbool, vanaf):
    """Slotkoersen van de index vanaf `vanaf`. Faalt luid, niet stil."""
    import yfinance as yf

    start = (vanaf - timedelta(days=7)).strftime("%Y-%m-%d")
    hist = yf.Ticker(symbool).history(start=start, auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError(f"geen koersreeks voor {symbool} vanaf {start}")
    return {d.date(): float(c) for d, c in zip(hist.index, hist["Close"])}


def _koers_op_of_voor(reeks, dag):
    """Laatste slotkoers op of vóór `dag` — beurzen zijn dicht in het weekend.

    Maximaal 7 dagen terug: verder terug meet je een andere week en dat is een
    stille definitiefout in plaats van een ontbrekende meting.
    """
    for terug in range(8):
        k = reeks.get(dag - timedelta(days=terug))
        if k:
            return k, terug
    return None, None


def _datum(waarde):
    if not waarde:
        return None
    try:
        return datetime.fromisoformat(str(waarde).replace("Z", "+00:00")).date()
    except Exception:
        return None


def analyse(pad=STANDAARD_BESTAND, index=STANDAARD_INDEX):
    data = _lees_posities(pad)
    posities = data.get("positions") or {}

    open_pos, dicht_pos = {}, {}
    for naam, p in posities.items():
        (dicht_pos if str(p.get("status", "")).upper() == "CLOSED" else open_pos)[naam] = p

    vroegste = min((_datum(p.get("opened_at")) for p in open_pos.values()
                    if _datum(p.get("opened_at"))), default=None)
    if not vroegste:
        print("Geen open posities met een aankoopdatum — niets te meten.")
        return 1

    reeks = _index_reeks(index, vroegste)
    laatste_dag = max(reeks)
    index_nu = reeks[laatste_dag]

    print(f"Dip-koper tegen {index} — peildatum {laatste_dag}")
    print("=" * 78)
    print(f"{'naam':<12} {'gekocht':<11} {'inleg':>8} {'nu':>8} {'wij':>8} "
          f"{'index':>8} {'verschil':>9}")
    print("-" * 78)

    som_inleg = som_nu = som_index = 0.0
    onmeetbaar = []

    for naam, p in sorted(open_pos.items(), key=lambda kv: str(kv[1].get("opened_at"))):
        dag = _datum(p.get("opened_at"))
        inleg = float(p.get("cost_basis_usd") or 0.0)
        nu = float(p.get("current_value_usd") or 0.0)
        if not dag or inleg <= 0 or nu <= 0:
            onmeetbaar.append((naam, "geen aankoopdatum of bedrag in het positiebestand"))
            continue

        index_toen, terug = _koers_op_of_voor(reeks, dag)
        if not index_toen:
            onmeetbaar.append((naam, f"geen {index}-koers rond {dag}"))
            continue

        index_waarde = inleg * (index_nu / index_toen)
        ons_pct = (nu / inleg - 1) * 100
        idx_pct = (index_nu / index_toen - 1) * 100

        som_inleg += inleg
        som_nu += nu
        som_index += index_waarde

        print(f"{naam:<12} {str(dag):<11} {inleg:>8.2f} {nu:>8.2f} "
              f"{ons_pct:>+7.1f}% {idx_pct:>+7.1f}% {ons_pct - idx_pct:>+8.1f}pp"
              + ("  *" if terug else ""))

    print("-" * 78)
    if som_inleg <= 0:
        print("Niets meetbaar.")
        return 1

    ons_tot = (som_nu / som_inleg - 1) * 100
    idx_tot = (som_index / som_inleg - 1) * 100
    print(f"{'TOTAAL':<12} {'':<11} {som_inleg:>8.2f} {som_nu:>8.2f} "
          f"{ons_tot:>+7.1f}% {idx_tot:>+7.1f}% {ons_tot - idx_tot:>+8.1f}pp")
    print()
    print(f"  Ingelegd ${som_inleg:,.2f} is nu ${som_nu:,.2f} waard.")
    print(f"  Diezelfde dollars in {index} waren nu ${som_index:,.2f} geweest.")
    verschil = som_nu - som_index
    print(f"  Verschil: ${verschil:+,.2f} — de dip-koper "
          f"{'VERSLAAT' if verschil > 0 else 'BLIJFT ACHTER OP'} de index.")

    if onmeetbaar:
        print()
        print("  NIET MEEGETELD (onmeetbaar is niet nul):")
        for naam, reden in onmeetbaar:
            print(f"    {naam}: {reden}")

    if dicht_pos:
        gerealiseerd = float(data.get("realized_pnl_usd") or 0.0)
        print()
        print("  ⚠️  OVERLEVINGSVERTEKENING — lees dit vóór de conclusie hierboven.")
        print(f"    Dit overzicht bevat alleen posities die NOG OPEN staan. De "
              f"{len(dicht_pos)} gesloten posities ({', '.join(sorted(dicht_pos))}) "
              f"zitten er niet in,")
        print(f"    en dat zijn juist de posities die niet werkten: samen "
              f"${gerealiseerd:+,.2f} gerealiseerd. Een vergelijking die alleen naar")
        print("    de overlevers kijkt, vleit per definitie.")
        print()
        netto = verschil + gerealiseerd
        print(f"    Ruwe correctie: ${verschil:+,.2f} voorsprong op de open posities "
              f"${gerealiseerd:+,.2f} gerealiseerd = ${netto:+,.2f}.")
        print(f"    Dat is nog steeds geen zuivere vergelijking — van de gesloten "
              f"posities is niet meer te achterhalen")
        print("    wat de index in HUN periode deed, want quantity en cost_basis "
              "gingen bij de close naar 0.")
        print(f"    Sinds 2026-08-12 bewaart de sleeve realized_pnl_usd én "
              f"entry_cost_basis_usd per positie, dus vanaf de")
        print("    eerstvolgende close is dit wél zuiver te berekenen.")

    print()
    print(f"  ⚠️  {len([1 for _ in open_pos]) - len(onmeetbaar)} posities over "
          f"{(laatste_dag - vroegste).days} dagen. Dat is een eerste aflezing, "
          f"geen bewijs — de poort in PLAN_2026-08 vraagt zes maanden.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Dip-koper tegen de wereldindex")
    ap.add_argument("--file", default=STANDAARD_BESTAND)
    ap.add_argument("--index", default=STANDAARD_INDEX)
    args = ap.parse_args()
    try:
        return analyse(args.file, args.index)
    except Exception as e:
        print(f"FOUT: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
