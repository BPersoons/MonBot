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

### Controle-agent (ontwerp, 22-09): **GO-mits** voor de bouw van `utils/proeftuin.py`, **STOP** voor de migratie van de dip-koper
*(De bouwer heeft het oordeel letterlijk overgenomen: de controle-agent heeft alleen leesrechten.)*

**Blokkerend:**
1. **Invariant 2 wordt alleen bij de start gecontroleerd, maar het dip-potje kiest zijn munten tijdens het draaien.** `XYZ-TSM` en `XYZ-ASML` staan CONFIRMED in de themalijst van de dip-koper. De overlap-check moet dus bij elke order gebeuren, en de ticker moet eerst genormaliseerd worden.
2. **Het kasbeheer is een tweede partij op deze wallet.** G2 (FUND_SLEEVE) en G3 (SLEEVE_REBALANCE) sturen het wallet-totaal naar min($500, 10%). Daardoor trekken ze potjeskas weg, en vullen ze na een kill het potje weer aan, buiten het proeftuinbudget om.
3. **De potjesstatus staat in de image** (`config/experimenten.json`, niet gemount). Een deploy wist dus een kill.

**Belangrijk:**
4. **De meter per potje ontbreekt.** H3 ziet een potje zonder `sleeve` niet. Alle potjes vallen onder één potjesnaam. Stromen kennen geen oogst, en Check 20 corrigeert niet voor stromen.
5. **Het hergebruikte ordepad boekt een deelvulling als volledig** (IOC 5%). Mislukt `set_leverage`, dan volgt alleen een waarschuwing; TSM en ASML zijn maximaal 10x isolated.
6. **Invariant 4 botst met het eigen plan.** De uitvoeringstest van 2×$12 haalt de grens niet, en de afroming van potje 1 ook niet. "Oogst naar de kern" kan code niet uitvoeren, want de kern staat bij DeGiro.
7. **Op welke wallet draait de uitvoeringstest?** Op 0xBd6c botst hij met de dip-koper, en valt hij buiten de NAV.
8. **Het risico verschuift naar de configvalidatie.** `utils/motor.py` laat NaN en `True` door als budget. Nodig: een strikt schema (onbekende sleutel = weigeren), vaste eenheden en een liquiditeitsvloer (TSM ~$1,9 mln per dag, ASML ~$0,8 mln).
9. **State onder `data/` zit niet in de deploy-backup.**
10. **Klein:**
    - budget als inleg tegenover budget als maximale blootstelling;
    - `instap: direct` zonder controle op beursuren en prijs;
    - de sweep verplaatst alle spot-USDC.

**De migratie is hoog risico met weinig leerwaarde.** Het positiebestand heeft 10 lezers en trade_log ~12 guards. Mogelijke gevolgen: een valse daling van ~$287, een sprong in H1 van ~$29 en dubbeltelling. Bovendien is het daarna een ander experiment. **Advies:** eerst op 25-09 beslissen. Stopt de dip-koper, dan krijgt de motor een lege wallet. Gaat hij door, dan krijgt de motor een eigen wallet.

**Levert de configuratie-aanpak tijd op? Deels.**
- De motor is groter dan de dip-koper zelf.
- Er is ruimte voor 2-3 potjes van ~$80.
- Het voorbeeldmandje is een koop-en-houd-these, en die is volgens MOTOR 2b op papier te meten.
- Alleen de moeite waard als slanke versie 1: vaste mandjes, alleen xyz, een lege of nieuwe wallet, geen dip-signaal.

**Antwoorden op de open vragen:**
- **Controle tegen HL:** elke cyclus, per munt (grootte en hefboom). Bij een verschil stopt alleen dat potje met kopen; het beheert zijn uitstap nog wel (min(state, HL), `reduceOnly`) en meldt.
- **Kill-orders:** marktorders zijn op deze omvang verantwoord (TSM-spread 0,018%, ASML 0,041%). Gebruik wel een IOC-limiet van 1-2% vanaf de mid en boek de werkelijke vulling.
- **Funding** hoort in het resultaat. Gemeten ~5,5% per jaar.

**Pre-mortem:**
- de migratiedag;
- G3 haalt potjeskas weg;
- posities worden samengevoegd;
- een weesrest na een deelvulling;
- een deploy wist de kill;
- 10x hefboom.

Daarnaast heeft het budget geen marge: $500 × 50% is precies $250. Een kill is een trigger, geen plafond. Zet de kill daarom op ~40%.

**Gemiste kansen:**
- stops op de beurs (reduceOnly-triggerorders);
- EQQQ op 25-09 maakt de wallet leeg;
- subaccounts op HL.


## Reactie bouwer (22-09)

**Overgenomen, met een koerswijziging: de motor wordt nu NIET gebouwd.**

Het beslissende argument is dat van de controle-agent: er is nog geen experiment dat echt geld nodig heeft.
- Crypto vol-targeting: gestopt.
- TSMC+ASML: een koop-en-houd-these, dus op papier te meten (MOTOR 2b).
- Centrus: VOLGEN.
- Geheugen: afvaller.

Een motor bouwen die groter is dan de dip-koper, voor 2-3 potjes van $80 die niets leren wat papier niet leert, maakt tijd juist wél de blokker.

**In plaats daarvan:**
1. **Schaduwpotjes (research-lijn, geen geld, geen geldcode):** elk uitschieter- of mandjesidee draait vooruit met zijn eigen regels (stop, laten lopen, trailing, oogsten) op dagkoersen, tegen WEBN, met ~5,5% per jaar funding voor HL-perps. Zoveel tegelijk als er ideeën zijn. Dit levert het meeste van wat een geldpotje zou leren, behalve fills en deelvullingen.
2. **De geldmotor wordt pas gebouwd als een schaduwpotje promotie verdient.** Dan als slanke versie 1:
   - vaste mandjes, alleen xyz, geen dip-signaal;
   - een lege of eigen wallet, of subaccounts als de hoofdwallet $100k volume heeft (HL-docs: sub-accounts vanaf $100k volume, ieder met een eigen clearinghouseState);
   - stops op de beurs vanaf dag 1;
   - voorwaarden 1-9 van deze review, en een kill op 40% zodat de som van (budget × kill%) onder $250 blijft.
3. **Migratie van de dip-koper: van tafel.** Op 25-09 wordt beslist: stoppen (posities sluiten met reduceOnly) of doorgaan zoals hij is.
4. **Bevinding 8 (NaN en `True` als budget in `utils/motor.py`):** hersteld in de volgende commit, want dat is bestaande code.
5. **Bevinding 2 (G2/G3 op de dip-koper-wallet):** geldt ook nu. Het kasbeheer stuurt die wallet naar min($500, 10%). Dat wordt meegenomen in de evaluatie van 25-09.

