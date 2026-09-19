# Claimblad — Fluid aanzetten (M3) + saldi lezen los van de `automated`-vlag

*Datum: 2026-09-19 · Poort: A1 (geldcode: saldo-lezing) **en** A2 (kapitaalbeweging ~$872 naar een nieuw protocol) · Mijlpaal: M3*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert

**Deel 1 — code (A1), al gebouwd en getoetst, nog niet gedeployd.**
Drie lussen die saldi lezen, filterden op `automated`. Die vlag zegt of er automatisch geld **heen** mag, niet of er geld **ligt**. Gevolg: zodra een protocol op `automated: false` gaat, verdwijnt het geld uit alle totalen — de valse drawdown uit bevinding 6 van 15-09.
- `agents/treasury_agent.py::_get_yield_balances` — filter weg; leest nu strikt (`lees_aave_saldo` / `lees_erc4626_saldo`) en laat een onleesbaar protocol **uit** de dict in plaats van op 0 te zetten.
- `utils/verliesbewaking.py::_saldi_onchain` — filter weg; een onbekend type geeft een waarschuwing.
- `utils/treasury_executor.py::get_total_yield_balance` — filter weg; ingeslikte fout is nu een waarschuwing.
- Nieuw in `utils/treasury_executor.py`: `lees_aave_saldo` en `lees_erc4626_saldo` — strikte varianten die **doorgooien**. De bestaande `get_*`-functies roepen ze aan en houden hun 0.0-gedrag voor logregels.
- Toetsen: `tests/test_yield_saldi.py` (13). Eén bestaande toets in `tests/test_verliesbewaking.py` legde het oude gedrag vast en is omgedraaid, met de reden erbij.

**Deel 2 — besluit (A2): Fluid van `automated: false` naar `true`** in `config/treasury_protocols.json` (zit in de image, dus via een deploy).

Wat er daarna mechanisch gebeurt, zonder verdere tussenkomst:
1. De volgende volledige kasbeheerronde ziet Aave op **100%** van het rendementspotje, boven de drempel van 80%.
2. Diversificatie maakt één YIELD_SWITCH-voorstel met `switch_amount_usd` ≈ **$871,78** (Aave terug naar 65%), bestemming Fluid.
3. De executor neemt dat deelbedrag op uit Aave en stort het in de fUSDC-vault.
4. Daarna doe ik met de hand een **proef-opname van $10** uit Fluid (M3-eis). Die $10 blijft op de treasury-wallet staan; dat telt gewoon mee in het potje (`source_map: treasury_wallet_usdc → yield_core`) en is te klein voor een nieuwe deploy (`_MIN_DEPLOY_USD` $100).

## Beweringen

| # | Bewering | Bewijs |
|---|---|---|
| F1 | **Rendement nu:** Fluid 4,43% (risico-gecorrigeerd 3,78%), Aave Arbitrum 2,92% (2,85%). Fluid-vault TVL $62,2 mln, `immediate_withdraw: true`. | `get_yield_opportunities()` in de container, 19-09 ~08:15 UTC. |
| F2 | **Er komt géén volledige overstap.** De YIELD_SWITCH-drempel is 1,5pp risico-gecorrigeerd; het verschil is 0,93pp. | `agents/treasury_agent.py:81` (`_YIELD_SWITCH_MIN_SPREAD`), `:1579`. |
| F3 | **Wat er wél gebeurt:** diversificatie bij > 80% concentratie, terug naar 65%. Saldo nu: Aave $2.490,81, rest $0 → te verplaatsen **$871,78**. | `agents/treasury_agent.py:143-146`; gemeten saldi in de container. |
| F4 | **Opbrengst:** $871,78 × (4,43 − 2,92) = **+$13,2/jaar**. Bij de huidige kostenbasis van $0,282/dag dekt dat ~15% van het H1-tekort. | Rekensom uit F1 en F3. |
| F5 | **Bovengrens per protocol: 65%** van het rendementspotje voor elk niet-benchmark-protocol, uit één bron (`config/experimenten.json`), met 0,65 als terugval bij een onleesbaar register. | `agents/treasury_agent.py:113-131`, gebruikt op 4 plekken (`:877`, `:1369`, `:1567`, `:1708`). |
| F6 | **Bevinding 1 van 15-09 (diversificatie nam het hele saldo) is dicht:** de executor gebruikt `switch_amount_usd` en rondt naar beneden af op centen. | `utils/treasury_executor.py` YIELD_SWITCH-tak, `deel = int(float(switch_amount) * 100) / 100`. |
| F7 | **Bevinding 2 (afronding → revert, en een revert die tóch werd verstuurd) is dicht:** een volledige opname vraagt `type(uint256).max`, en `_simulate_tx` gooit een revert door in plaats van hem als "RPC weg" te behandelen. | `withdraw_aave_to_wallet(..., volledig=True)`; `_simulate_tx` met `_is_revert`. |
| F8 | **Bevinding 3 (100% naar Fluid zodra de APY ≥ 4,90%) is dicht** door F5. | Zie F5. |
| F9 | **Bevinding 4 (Check 24 niet in de container) is dicht**, en er kwamen twee bewakers bij: Check 25 (gestrand geld) en Check 26 (gas). | `docker exec … grep -c` op de draaiende image, 17-09. |
| F10 | **Bevinding 5 (gasbuffer) is dicht:** treasury-wallet 0,000474 ETH ≈ 95 transacties; hoofdwallet 0,000147 ≈ 27 bridges. | Bijvulling 17-09, tx `0xd737af52…`. |
| F11 | **Bevinding 6 (valse drawdown bij terugdraaien) is dicht** door deel 1. Toets: het saldo blijft in het totaal als de vlag uitgaat. | `tests/test_yield_saldi.py::test_terugdraaien_naar_automated_false_geeft_geen_valse_drawdown`. |
| F12 | **Bevinding 7 (onbegrensde retry-lus na een mislukte deposit) is dicht:** `_deploy_geblokkeerd` stopt na 2 fouten in 24 u, met één melding. | `agents/treasury_agent.py:798-828`. |
| F13 | **Bevinding 8 (2/3 direct opneembaar) speelt hier niet:** Fluid is `immediate_withdraw: true`, en een vault die dat niet is (Gains) is sowieso uitgesloten als automatische bestemming. | `agents/treasury_agent.py` liquiditeitsfilter in `_pick_best_protocol` en in de diversificatie. |
| F14 | **Het geld blijft zichtbaar in de potjesreeks:** `yield_balances.fluid-fusdc-arbitrum → yield_core` staat in `config/sleeves.json`, en onbekende protocollen vallen terug op het standaardpotje. | `config/sleeves.json` `source_map`; `utils/sleeve_nav.py:119-124`. |
| F15 | **Toetsen:** volledige suite 427 groen, pre-deploy-poort GROEN (state-audit, syntax, pytest, pipeline 132/0). Mutaties op deel 1: **6/6 rood** (`mut_saldi.py`: filter terug, milde lezer, onbekend type als nul, fout als nul, geen vault als nul, lege convertToAssets als nul). | `python scripts/predeploy.py`; plugin in de scratchpad. |

## Raakt deze KPI's / poorten

- **M3:** na uitvoering resteren de metingen: proef-opname van $10 en **14 dagen gemeten APR ≥ 4%, binnen 1pp van DeFiLlama**.
- **H1:** +$13,2/jaar opbrengst (+$0,036/dag) tegenover een tekort van ~$0,09/dag.
- **H2:** het rendement van het veilige potje stijgt van 2,92% naar ~3,45% gewogen; het doel is Aave + 2pp, dus dit alleen is niet genoeg.
- **H3:** dit is **geen experiment uit het verliesbudget van $250** maar een rendementsprotocol binnen het veilige potje. Dat maakt het bedrag ($872) groter dan het experimentbudget: zie het risico hieronder.

## Risico en terugdraaien

- **Maximaal op het spel: $871,78** (16% van het vermogen) bij een exploit of een bevroren vault. Fluid is een lending-protocol; de fUSDC-vault heeft $62,2 mln TVL en directe opname.
- **Opnamelimieten** groeien per blok mee; bij stress kan een grote opname tijdelijk beperkt zijn. Onze $872 is klein ten opzichte van de vaultomvang.
- **Nieuw protocol = nieuwe venue.** Volgens de kaders vraagt dat Barts akkoord, ook al staat M3 in het plan. Dat wordt gevraagd vóór uitvoering.
- **Terugdraaien:** `automated: false` + deploy (kost één ronde) en handmatig `withdraw_erc4626_to_wallet(vault, key)`; kasbeheer zet het daarna terug in Aave. Sinds deel 1 geeft dat **geen** valse drawdown meer.
- **Bewaking na de zet:** Check 24 kijkt elke ronde naar share price en saldo per protocol (alarm bij elke daling, kill bij −1%), Check 26 naar het gas, en de dagelijkse KPI-run naar het potje.

## Wat ik zelf niet heb gecontroleerd

- **De vaultcode van Fluid.** Ik leun op TVL, de audits van derden en het feit dat opname direct is; ik heb de contracten niet gelezen.
- **Of de diversificatie precies één voorstel maakt.** Dat is de bedoeling (cooldown 12 u), maar het is nooit in productie gedraaid — ik kijk mee bij de eerste ronde.
- **Het rendement na kosten.** Eén Aave-opname (~$0,01 gas) plus één deposit; bij $13/jaar is dat verwaarloosbaar, maar de 14-daagse meting moet het bevestigen.
- **Het gedrag bij een geblokkeerde opname.** De proef-opname van $10 is precies bedoeld om dat te toetsen vóór we erop vertrouwen.

---

## Audit

*Controle-agent, 2026-09-19 (overgenomen door de bouwer).*

**Oordeel A1 (code, saldo-lezing): GO-mits - Oordeel A2 (besluit ~$872 naar Fluid): STOP.**

**Blokkerend**
1. **De meter voor de M3-poort bestaat niet.** `min_apr_pct`, `max_afwijking_defillama_pp` en `min_dagen` staan alleen in `config/experimenten.json`; geen regel code leest ze, en `utils/kpi.py` kent geen APR per protocol. Ook de kill-regel `dagen_onder_benchmark: 30` wordt nergens geevalueerd. "Geen experimentgeld voor de meter er staat."
2. **Het besluit is niet "$872", maar "tot 65% van het veilige potje, automatisch".** Droogloop met de echte config: bij een ruwe Fluid-APY >= **5,10%** vuurt een tweede switch van $747,25 en landt Fluid op exact 65% = **$1.619**. Die drempel werd op **90 van de laatste 180 dagen** gehaald.
3. **De noemer van "16%" is de gunstigste.** Van het kapitaal dat verplaatst mag worden (zonder de broker) is $871,78 **28%**, van het veilige potje **35%**; de structurele bovengrens is 51% van het beweegbare kapitaal.

**Belangrijk**
4. **De beslissing draait op het milde saldo-dict**, waarin een ontbrekend protocol precies als nul telt. Gemeten: een onleesbaar Aave-saldo geeft een goedgekeurde switch die **$305 uit Fluid** trekt; een onleesbaar Fluid-saldo een switch van **$566 erheen**. De strikte guard bestond alleen richting een niet-benchmark.
5. **De nieuwe "strikte" lezers geven nog steeds een stille nul bij `"0x"`**, terwijl `verliesbewaking._saldi_onchain` daar terecht opwerpt - en de nieuwe toets legde dat verkeerde gedrag vast als bedoeld.
6. **De bewaking hangt aan een RPC.** Gemeten in de container: 1rpc 403, ankr "API key required", alleen Tenderly werkt. De oracle had 3 endpoints, de executor 7.
7. **Detectie is geen bescherming.** Check 24 meldt bij een share-price-daling maar handelt niet; bij een incident is het geld weg voor iemand Telegram leest.
8. **De poort is krap en meet de verkeerde vraag.** 14d-gemiddelde 4,16% tegen een eis van 4,0%; en een absolute eis faalt als de rente overal daalt, terwijl de hypothese "meer dan Aave" is.
9. **Volgorde:** `main.py:482` draait een volledige treasury-run op cyclus 1, dus de deploy die de vlag omzet verplaatst het geld binnen een minuut.
10. **De proef-opname van $10 bewijst te weinig** en komt na de inleg; een simulatie op het volle bedrag of een handmatige rondgang van ~$50 is sterker.

**Klein:** 11. gemounte `config/sleeves.json` op de VM mist Fluid in `source_map`/`venue_map`. 12. bevinding 9 van 15-09 (Morpho pool-id) niet geadresseerd en nog live: Fluid is de enige automatische bestemming. 13. `_DIVERSIFY_TARGET_PCT` hardcoded naast het register. 14. een mutatie overleeft; het `else`-blok in `_saldi_onchain` verandert de som niet. 15. compound-v3 geeft elke 5 minuten een waarschuwing. 16. F4 rekent 15% van het tekort, elders staat 40%.

**Zonder bevinding:** F1, F2, F3, F5-F7, F9, F10, F12, F13 zelf nagerekend of gemeten; de cap werkt aantoonbaar (switch geknipt op $747,25, landt op exact 65%); een voorstel per ronde; guard-dekking `automated` compleet (drie lussen, alle verbruikers lopen erdoorheen); 427 toetsen groen, predeploy GROEN, 6/6 mutaties rood.

**Voorwaarden voor A2:** meter gebouwd en getoetst - bevinding 4 en 5 gerepareerd - het juiste bedrag aan Bart voorgelegd - uitstap getoetst voor de inleg - twee deploys - `sleeves.json` op de host bijgewerkt - vastgelegd wat er gebeurt bij 3,9%.

## Reactie bouwer

*2026-09-19. De A2 is ingetrokken; Fluid blijft op `automated: false` tot alle voorwaarden af zijn.*

| # | Status | Wat |
|---|---|---|
| 1 | **opgelost** | Nieuw: `utils/rendement.py` plus de reeks in Check 24 (`_boek_rendementsmeting`). De share price en Aave's liquidityIndex lopen alleen op met rendement, dus twee metingen geven een flow-gecorrigeerde APR. De meter kent de poort (`min_apr_pct`, `min_dagen`, afwijking van DeFiLlama), de **spread tegen Aave over hetzelfde venster** en de kill-regel (`dagen_onder_benchmark`, via een dagreeks). `gehaald` is True/False/**None**. Het register koppelt nu expliciet `protocol_id`. 15 toetsen, 9/9 mutaties rood. |
| 2 | **overgenomen** | Het besluit dat aan Bart wordt voorgelegd luidt voortaan "tot 65% van het veilige potje ($1.619 vandaag), nu $872", met de 90-van-180-dagen erbij. |
| 3 | **overgenomen** | Idem: 28% van het beweegbare kapitaal, 35% van het veilige potje. |
| 4 | **opgelost** | `_switch_en_diversificatie` beslist nu op `_strikte_yield_saldi()`, ook richting de benchmark. Is die None, of mist er een protocol dat het milde dict wel kent, dan gebeurt er niets. Toetsen: onleesbaar geeft geen beweging; sleutelverschil geeft geen beweging; de strikte bedragen worden gebruikt. |
| 5 | **opgelost** | `_saldo_uit_antwoord()` gooit bij een leeg antwoord; alleen 32 nulbytes is een echte nul. Mijn eigen toets is omgedraaid. |
| 6 | **opgelost** | De oracle deelt nu de RPC-lijst van de executor (7 in plaats van 3). |
| 7 | **erkend, open** | Check 24 meldt en handelt niet. Dat blijft zo tot een automatische opname gebouwd en getoetst is; het staat als voorwaarde bij het A2-besluit. |
| 8 | **naar Bart** | De poort wordt niet opgerekt. Wat er gebeurt bij 3,9% is een besluit dat voor de zet vastligt. |
| 9 | **overgenomen** | Twee deploys. Deze ronde gaat alleen de code mee; de vlag blijft `false`. |
| 10 | **overgenomen** | De uitstap wordt getoetst voor de inleg (simulatie op het volle bedrag, of een handmatige rondgang van ~$50). |
| 11 | **open** | `config/sleeves.json` op de host: doen voor er geld naar Fluid gaat. |
| 12 | **open** | Morpho als tweede bestemming uitzoeken (pool-id). Nu is er geen alternatief. |
| 13 | **opgelost** | Het diversificatiedoel is `min(_DIVERSIFY_TARGET_PCT, cap uit het register)`. |
| 14 | **opgelost** | Een protocol met een adres maar zonder leesroute gooit nu (storing); zonder adres is het gewoon uit. |
| 15 | **opgelost** | Compound zonder adres geeft geen waarschuwing meer, alleen een debugregel. |
| 16 | **erkend** | Slordig: $0,036/dag is 13% van de kostenbasis en 40% van het tekort. |

**Toetsen na deze ronde:** 449 groen, pre-deploy-poort GROEN, mutaties 6/6 (saldi) en 9/9 (meter) rood.
