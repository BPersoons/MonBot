# Proeftuinmotor — een experiment met geld is een regel in het register, geen nieuwe code

*Ontwerp 2026-09-22 · status: **GEPARKEERD** na de ontwerpreview (`docs/audits/2026-09-22-proeftuinmotor-ontwerp.md`, GO-mits
voor de bouw, STOP voor de migratie). Te vroeg: er is nog geen experiment dat echt geld nodig heeft. Eerst
**schaduwpotjes** (`research/schaduwpotjes.py`); de geldmotor wordt gebouwd zodra een schaduwpotje promotie
verdient, als slanke versie 1 met de negen voorwaarden uit de review.*

## Waarom

Bart (22-09): "$500 in totaal, maar goed nadenken hoe we dit het slimste inzetten om zoveel
mogelijk, goed, te testen. Het zou zonde zijn om tijd onze blokker te laten zijn."

Tot nu toe was elk experiment met geld nieuwe code: de dip-koper is 1.800 regels, en elke
wijziging vraagt een audit. Op 21-09 vond de controle-agent in die code nog twee sluitpaden zonder
`reduceOnly`. Dat maakt tijd de blokker: niet het geld, maar het bouwen en toetsen per idee.

**De motor keert dat om.** Eén keer bouwen en één keer toetsen. Daarna is een nieuw potje een
configuratie in `config/experimenten.json`, en de controle-agent toetst alleen die configuratie
(A2, kapitaal), niet steeds nieuwe code.

## Wat één potje is

```json
"schakel_ai_tolhuisje": {
  "trede": 3, "status": "live", "budget_usd": 80,
  "motor": {
    "wallet": "thematic",
    "instrumenten": ["xyz:TSM", "xyz:ASML"],
    "weging": "gelijk",
    "instap": "direct",
    "uitstap": {
      "stop_verlies_pct": 40,
      "winst_laten_lopen_tot_pct": 100,
      "trailing_na_drempel_pct": 30,
      "oogst_boven_x_budget": 2.0
    },
    "kill_potje_verlies_pct": 50,
    "benchmark": "WEBN.DE",
    "evalueer_op": "2027-03-22"
  }
}
```

- **instap** is `direct` (kopen bij de start) of een benoemd signaal dat al bestaat en getoetst
  is (`dip` = het pullbacksignaal van de dip-koper). Nieuwe signalen zijn code en blijven daarom
  een eigen audit vragen. De motor versnelt configuraties, geen nieuwe logica.
- **uitstap** kent alleen de regels uit `docs/MOTOR.md` en het uitschieterontwerp:
  - een harde stop per positie;
  - winst laten lopen tot een drempel, daarna een trailing stop;
  - het overschot boven 2× het budget naar de kern.
- **kill_potje_verlies_pct**: verliest het potje als geheel 50% van zijn inleg, dan sluit de
  motor alles met `reduceOnly` en zet het potje op `gestopt`. Het register houdt het bij.

## Harde invarianten (elk met een toets die rood wordt als hij weg is)

1. **Elke verkoop is `reduce_only=True`.** Elke aankoop heeft hefboom 1 en `isolated`.
2. **Eén munt hoort bij hooguit één potje per wallet.** Hyperliquid telt posities per account
   per munt. Hielden twee potjes dezelfde munt, dan kon de verkoop van het ene potje de positie
   van het andere sluiten. De configuratie wordt geweigerd bij overlap.
3. **Som van de budgetten op trede 3 ≤ proeftuinkapitaal** (`globaal.proeftuin_kapitaal_usd`,
   $500). `utils/motor.py` meldt het al. De motor weigert te kopen boven het budget.
4. **Elke geplande order ≥ 2× de minimumorder van de beurs.** Zo niet, dan weigert de motor het
   potje bij de start, en schuift hij niet stil een tranche op (de les van de winstladder).
5. **Een onleesbaar statebestand stopt de motor luid.** Geen leeg potje (de les van 21-09).
   De state staat onder `data/`, is dus gemount, en wordt in-place geschreven.
6. **Geen 'gedaan'-vlag vóór de order slaagt.** Een order die HL weigert, geeft na N pogingen
   een melding, geen stil opnieuw proberen (A1-audit 21-09, ronde 2, bevinding c).

## Eén motor per wallet

Twee motoren op één wallet botsen: posities per munt worden samengevoegd, en de losse
kasadministraties tellen dezelfde USDC dubbel. Daarom:

- **Voorstel:** de motor neemt na de evaluatie van 25-09 de dip-koper-wallet (0xBd6c) over. De
  dip-koper wordt daarin **potje 1** (`instap: dip`, met zijn huidige uitstapregels), en zijn
  posities en geschiedenis (`gesloten_rondes`) migreren. Tot de migratie blijft de dip-koper
  ongewijzigd draaien en koopt de motor niets.
- **Alternatief:** een eigen wallet. Dat betekent een nieuwe sleutel, een nieuw secret en extra
  overboekingen. Meer onderdelen om te bewaken, dus alleen als de migratie niet lukt.

## Meten

- **Per potje uit de bron.** Omdat een munt maar bij één potje hoort, zijn de Hyperliquid-fills
  en de funding per munt ook per potje (`scripts/dipkoper_resultaat.py` wordt de meter van de
  motor). Het eigen boek is alleen voor de sturing, de bron is HL.
- **Tegen de benchmark over dezelfde periode, en met de beta erbij** (`scripts/blootstelling.py`).
- **Verliesbewaking** (Check 24) krijgt per potje de kill en het alarm (−25%), uit het register.

## Bouwvolgorde

1. **Ontwerpreview** (controle-agent, dit document).
2. `utils/proeftuin.py`: configvalidatie (invarianten 2-4), orders (hergebruik van
   `_close_or_trim` en de order-guards van de dip-koper), per-potje-state, kill en oogst.
   Plus toetsen per invariant, met mutaties.
3. **Code-review (A1)**, deploy zonder geld: de motor draait, maar er staat geen potje live.
4. **Uitvoeringstest** met één potje van ~$25 (twee munten van $12): kopen, deelverkoop, sluiten.
   Het doel is niet rendement, maar zien dat elk pad echt werkt.
5. Migratie van de dip-koper tot potje 1 (A2), en daarna de eerste echte potjes.

## Open vragen voor de review

- Is "één munt per potje per wallet" genoeg, of moet de motor bij elke cyclus ook controleren
  dat de HL-positie per munt gelijk is aan de som in de state? (Voorstel: ja, en bij verschil
  stoppen.)
- De kill bij −50% sluit met marktorders. Is dat bij dunne xyz-markten (TSM, ASML) verantwoord,
  of is een limietorder met een maximale slippage nodig?
- Funding: stock-perps op xyz kosten de lange kant ~4-5% per jaar. Hoort dat in de
  benchmarkvergelijking, of apart gemeld?
