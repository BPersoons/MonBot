# Claimblad — proeftuinmotor (ontwerp)

*Datum: 2026-09-22 · Poort: A1-ontwerp (vóór de bouw van geldcode) · Mijlpaal: motor/proeftuin*

> Voor de controle-agent. Beoordeel het ONTWERP in `docs/PROEFTUIN_MOTOR.md`, niet code (die bestaat nog niet).

## Wat er verandert
- Nieuw ontwerp: `docs/PROEFTUIN_MOTOR.md`. Nog geen code, geen deploy, geen geldbeweging.
- Doel: een experiment met geld wordt een configuratie in `config/experimenten.json` in plaats van nieuwe code; één A1 voor de motor, daarna per potje een A2 op de configuratie.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Twee motoren op één HL-wallet botsen (positie per munt samengevoegd, kas dubbel geteld), dus één motor per wallet. | HL telt posities per account per munt (clearinghouseState); `utils/thematic_exposure_lab.py` houdt `cash_usd` in een eigen bestand bij |
| 2 | Met "één munt per potje per wallet" zijn HL-fills per munt = per potje, zodat meten uit de bron kan. | `scripts/dipkoper_resultaat.py` (per munt) |
| 3 | De zes invarianten dekken de faalpatronen van dit project (reduceOnly, $10-minimum, leeg potje, 'gedaan' vóór succes, budget). | docs/valkuilen.md; audits 21-09 |
| 4 | De motor versnelt configuraties, geen nieuwe signalen: een nieuw instapsignaal blijft code met eigen audit. | ontwerp § "Wat één potje is" |

## Risico en terugdraaien
- Dit is een ontwerp: er staat niets op het spel tot stap 3. Het grootste ontwerprisico is de migratie van de dip-koper (positie- en geschiedenisoverdracht).

## Wat ik zelf niet heb gecontroleerd
- Of HL xyz-markten voor TSM/ASML diep genoeg zijn voor marktorders bij een kill.
- Of subaccounts op HL een betere scheiding zouden geven dan "één munt per potje" (voorwaarden onbekend).

---

## Audit
*(in te vullen door de controle-agent)*

## Reactie bouwer
*(per open punt)*
