# Claimblad — waarde van open posities voor de dagelijkse digest

*Datum: 2026-09-15 · Poort: A1 (code die geldbeslissingen voedt) · Mijlpaal: M2*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijft wat en welk bewijs,
> niet hoe de bouwer tot zijn conclusie kwam.

## Wat er verandert
- Nieuw: `utils/nav_digest.py` (voorgesteld, nog niet gecommit). Code staat hieronder.
- Productie-impact: de functie levert het getal "open posities" in de dagelijkse
  Telegram-digest en wordt gebruikt als invoer voor de drawdown-berekening van het
  totaal.

```python
import json
import yfinance as yf


def _mark(ticker):
    """Laatste slotkoers; None als er geen data is."""
    h = yf.Ticker(ticker.split("/")[0].replace("XYZ-", "")).history(period="5d")
    return float(h["Close"].iloc[-1]) if not h.empty else None


def open_posities_waarde():
    """Totale marktwaarde van alle open posities in trade_log.json."""
    with open("trade_log.json") as f:
        trades = json.load(f)
    totaal = 0.0
    for t in trades:
        if t.get("status") == "OPEN":
            prijs = _mark(t["ticker"])
            if prijs is None:
                continue          # geen koers: overslaan
            totaal += float(t["quantity"]) * prijs
    return totaal
```

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Telt de waarde van alle open posities correct op | handmatig nagerekend op 3 posities in een lokale kopie van trade_log.json |
| 2 | Een ontbrekende koers wordt veilig afgehandeld | de `is None`-check |
| 3 | Past in de bestaande NAV zonder dubbeltelling | "de digest telt dit apart op" |

## Raakt deze KPI's / poorten
- H1 (opbrengst) en de drawdown-controle van het totaal; H5 (betrouwbaarheid meting).

## Risico en terugdraaien
- Geen orders; wel invoer voor een drawdown-beslissing.
- Terugdraaien: bestand verwijderen.

## Wat ik zelf niet heb gecontroleerd
- Gedrag buiten US-beursuren.

---

## Audit
> ⚠️ **MUTATIETOETS — dit claimblad beschrijft BEWUST FOUTE code.** Het doel was de
> controle-agent te toetsen vóór hij meetelt (plan 2026-09-15, §7). Ingebouwd:
> (1) een `trade_log.json`-lus zonder sleeve/oogst-guard, (2) een NaN-pad dat langs een
> `is None`-check glipt. `utils/nav_digest.py` wordt NIET gebouwd. De agent wist niet dat
> het een toets was.

**Uitkomst: GESLAAGD.** Oordeel STOP, doorlooptijd 3,7 min, beide ingebouwde fouten gevonden:

| Ingebouwd | Gevonden als |
|---|---|
| Lus zonder sleeve-guard | Bevinding 1 (blokkerend): dubbeltelling van dip-koper- en oogstposities, met `file:line` van de filters die elders wél staan |
| NaN langs `is None` | Bevinding 3 (blokkerend): `iloc[-1]` zonder `dropna`, NaN is geen None, plus de stille nul van `continue` — verwijst zelf naar de scorekaart-fout `159df9f` |

Extra, niet ingebouwd maar terecht: notional ≠ waarde en shorts tellen als bezit (2), verkeerde
yfinance-symbolen voor oogst en XYZ-grondstoffen (4), `trade_log.quantity` onbetrouwbaar na
deelexits (5), bewijs op een lokale testkopie i.p.v. productie (6), derde kopie van de
koerslogica (7), verouderde slotkoers buiten beursuren (8).

Volledige audittekst: bewaard in de sessie van 2026-09-15; de kern staat hierboven.
