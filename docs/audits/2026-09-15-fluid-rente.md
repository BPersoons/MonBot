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
*(in te vullen door de controle-agent)*

## Reactie bouwer
