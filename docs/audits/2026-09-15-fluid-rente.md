# Claimblad — Fluid fUSDC als renteprotocol (spoor 1, M3)

*Datum: 2026-09-15 · Poort: **A2** (kapitaalbeweging) · Mijlpaal: M3 · Afhankelijk van: M2 (Check 24) eerst gedeployed*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijft wat en welk bewijs.

## Wat er verandert
- `agents/treasury_agent.py` — `_TRACKED` krijgt `("fluid-lending", "Arbitrum", "USDC", ...)`
- `config/treasury_protocols.json` — entry `fluid-fusdc-arbitrum`, `type: erc4626`, vault `0x1A996cb54bb95462040408c06122D45D6Cdb6096`, `automated: true`, `immediate_withdraw: true` (zit in de image, niet gemount)
- `utils/treasury_risk.py` — profiel `fluid-fusdc-arbitrum` (sc 0,85 · liquidity 0,85 · counterparty 0,90 · maturity 0,60)
- `tests/pre_flight/check_treasury.py` — Fluid in de lijst live protocollen
- `config/sleeves.json` — `source_map`/`venue_map` voor Fluid (host-kopie volgt in-place)

**Wat er na de deploy met geld gebeurt (verwachting, zelf te verifiëren):**
1. Fluid verschijnt in `opportunities` met APY ~4,3% en risico-gecorrigeerd ~3,69% (Aave: 2,53%).
2. `_check_yield_switch` doet **niets**: de spread op risico-gecorrigeerde APY is 1,16pp < `_YIELD_SWITCH_MIN_SPREAD` 1,5pp.
3. `_check_yield_diversification` **vuurt**: Aave = 100% van `yield_balances` > 80%. Verplaatst `2490 − 0,65 × 2490 ≈ $871` naar de beste andere automatische Arbitrum-bestemming met `immediate_withdraw` — dat is Fluid.
4. Uitkomst: ~$1.620 Aave / ~$870 Fluid. Verwachte meeropbrengst ~$15/jaar (35% × 1,7pp). **Lager dan de +$45–70 in het plan**; die ging ervan uit dat alles zou overstappen.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Het vault-adres is echt Fluid fUSDC op Arbitrum met native USDC | eth_call via Tenderly 2026-09-15: `name()` = "Fluid USD Coin", `asset()` = `0xaf88d065…5831`, `totalAssets` ≈ $61,2M, `convertToAssets(1e6)` = 1,1297 |
| 2 | Rendement structureel boven Aave | DeFiLlama pool `4c45cc9e…`: 701 punten sinds 2024-10-15, gem. 6,85%, laatste 180d 5,46%, min 180d 3,36% |
| 3 | De bestaande executor kan erin en eruit | `_deposit_erc4626` / `withdraw_erc4626_partial` in `utils/treasury_executor.py`, al gebruikt voor Morpho en Gains (ERC-4626) |
| 4 | Het geld blijft direct opneembaar | `immediate_withdraw: true`; ERC-4626 `withdraw`/`redeem` |
| 5 | Pre-flight dekt de nieuwe entry | `python -m tests.pre_flight.check_treasury`: 129 passed, incl. "profile defined for 'fluid-fusdc-arbitrum'" |
| 6 | Verlies in Fluid wordt snel gezien | Check 24 (`utils/verliesbewaking.py`): ERC-4626 share price mag nooit dalen; saldo flow-gecorrigeerd — **mits M2 eerst gedeployed** |

## Raakt deze KPI's / poorten
- M3-poort: 14 dagen gemeten APR ≥ 4% en binnen 1pp van DeFiLlama; proef-opname $10 slaagt.
- H1/H2 (rente-opbrengst), veilig-integriteit uit `config/experimenten.json`, `globaal.veilig_min_direct_opneembaar`.

## Risico en terugdraaien
- **Maximaal op het spel:** ~$871 (35% van het veilige potje) bij een smart-contract- of oracle-incident in Fluid.
- Fluid kent **opnamelimieten** die per blok meegroeien; bij stress kan een grote opname tijdelijk beperkt zijn.
- Gas: enkele centen op Arbitrum.
- **Terugdraaien:** `automated: false` voor Fluid in de config + deploy; handmatig `withdraw_erc4626_to_wallet(vault, key)` → kasbeheer zet het terug in Aave (DEPLOY_YIELD vanuit de treasury-wallet).

## Wat ik zelf niet heb gecontroleerd
- Of de diversificatie-proposal écht automatisch APPROVED wordt en welk pad hij in `advance_proposal` volgt (Aave partial withdraw → Fluid deposit).
- De actuele opnamelimiet van Fluid voor een bedrag van ~$871.
- Of `_deposit_erc4626` een `approve` vooraf doet die Fluid accepteert (Morpho werkte, Fluid nooit geprobeerd).
- Of Morpho-vaults ook in `opportunities` kunnen opduiken en de bestemming worden.
- Een proefstorting van een klein bedrag vóór de volledige verschuiving.

---

## Audit
**Oordeel A2 (controle-agent, 11,5 min): STOP.** Kern van de bevindingen:

| # | Ernst | Bevinding | Bewijs |
|---|---|---|---|
| 1 | blokkerend | Diversificatie vanuit **Aave** negeert `switch_amount_usd` en neemt het **hele** saldo op; ~$915 gaat naar Fluid, de rest wordt via DEPLOY_YIELD (APPROVED) alsnog naar de beste bestemming (Fluid) gezet → 65–100% in Fluid, niet 35%. Bestaande pre-flight-toets dekt dit niet. | `utils/treasury_executor.py:1112-1129`, `:1286-1292`; `agents/treasury_agent.py:817`, `:1930-1938` |
| 2 | blokkerend | `round(live_bal, 2)` kan boven het echte aUSDC-saldo uitkomen (2490,137 → 2490,14) → Aave-withdraw revert; `_simulate_tx` behandelt de JSON-RPC-error als "RPC unavailable" en verstuurt toch → FAILED + gas + 12u cooldown | `treasury_executor.py:126-137`, `:187-193`, `:1129` |
| 3 | blokkerend | Volledige APY-switch vuurt zodra Fluid ≥ ~4,90% — op 123 van de laatste 180 dagen — dan gaat 100% naar Fluid zonder besluit | DeFiLlama-charts; `treasury_agent.py:1364` |
| 4 | blokkerend | M2 (Check 24) staat nog niet in de container | `docker exec … os.path.exists` → False |
| 5 | belangrijk | Gasbuffer treasury-wallet 0,000124 ETH (~9 tx) | `treasury_executor.py:70` |
| 6 | belangrijk | Terugdraaien met `automated: false` terwijl er geld in Fluid staat → valse drawdown | `treasury_executor.py:854`, `risk_manager.py:286` |
| 7 | belangrijk | Mislukte deposit → onbegrensde DEPLOY_YIELD-retry-lus | `treasury_executor.py:1327-1332` |
| 8–9 | klein | 2/3-opneembaar-regel niet gehandhaafd in code; Morpho-pool-id wijst op DeFiLlama naar een ander product | — |

Gecontroleerd zonder bevinding: approve + deposit in fUSDC werken (state-override-simulatie: 871 USDC → 770,99 shares); opnamelimiet nu ruim ($13,3M withdrawable); Morpho kan geen bestemming worden (<$5M TVL); APY is puur base.

## Reactie bouwer
- **Fluid geparkeerd** (`automated: false`, `_status`-toelichting in `config/treasury_protocols.json`): allocator, switch en diversificatie filteren op `automated`, er staat nog geen geld in Fluid, dus bevinding 6 speelt niet. De M2-deploy verplaatst hierdoor geen kapitaal.
- **Bevinding 1, 2 en 7 zijn bestaande kasbeheer-bugs** die ook zonder Fluid bij elke toekomstige switch vanuit Aave toeslaan. Ze krijgen een eigen spoor (fix + toetsen + A1), vóór Fluid opnieuw ter A2 komt.
- **Bevinding 3 vraagt een besluit:** een harde cap per protocol in code (voorstel: max 65% van het veilige potje in één niet-Aave-protocol) is risicoverlagend en valt binnen de kaders; wordt voorgesteld in het volgende claimblad.
- **Bevinding 5:** ETH bijvullen is een handeling met eigen geld → wordt aan Bart gevraagd vóór de volgende Fluid-poging.
