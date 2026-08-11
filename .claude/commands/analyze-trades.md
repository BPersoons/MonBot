# /analyze-trades

Periodieke P&L analyse van de live trading swarm. Vergelijkt winners vs losers op signalen (TA/FA/SA), timeframe, richting en marktregime. Identificeert patronen en stelt concrete optimalisaties voor.

## Argumenten
- geen argument: analyseert alle trades sinds laatste deployment (CUTOFF = meest recente entry in trade_log vóór huidig tijdstip - 7 dagen)
- `full`: analyseert alle niet-geïmporteerde trades in de volledige history
- `since YYYY-MM-DD`: analyseert trades geopend na gegeven datum

## Uitvoering

### Stap 1 — Haal trade data op

Upload en run het analyse script op de live container:

```python
# scripts/_trade_analysis.py bevat de volledige analyse logica
# Gebruik gcloud scp + docker exec om te runnen
```

Kopieer `scripts/_trade_analysis.py` naar de VM en run:
```
gcloud compute scp scripts/_trade_analysis.py agent-trader-swarm-vm:/tmp/_trade_analysis.py --zone=europe-west1-b
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker cp /tmp/_trade_analysis.py agent_trader_swarm:/tmp/_trade_analysis.py && sudo docker exec agent_trader_swarm python /tmp/_trade_analysis.py'
```

Haal ook live posities op:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker exec agent_trader_swarm python /app/scripts/diag_positions_check.py 2>&1 | head -20'
```

### Stap 2 — Bereken metrics

Bereken voor de opgegeven periode:
- Win rate, Profit Factor, gemiddelde win/loss
- Total PnL (gerealiseerd + ongerealiseerd open)

### Stap 3 — Patroonanalyse: Winners vs Losers

Vergelijk gemiddelde signaalwaarden per groep:

| Metric | Winners | Losers | Verschil |
|---|---|---|---|
| TA score | ... | ... | ... |
| FA score | ... | ... | ... |
| SA score | ... | ... | ... |
| Conviction | ... | ... | ... |

Analyseer ook:
- **Close reason verdeling**: hoeveel stops, TPs, time exits?
- **Timeframe**: 1h Macro vs 4h Swing — welke presteert beter?
- **Richting**: BUY vs SELL — welke presteert beter?
- **sl_pct vs PnL**: brede stops = grotere verliezen?
- **sl_stage bij exit**: trades die stage ≥ 1 bereikten — hogere WR?
- **Marktregime bij entry**: BULLISH/BEARISH/NEUTRAL BTC 4h

### Stap 4 — Vergelijk met auto_params

Lees `config/auto_params.json` uit de container:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker exec agent_trader_swarm cat /app/config/auto_params.json'
```

Check of huidige drempelwaarden (`score_threshold`, `tech_prefilter_min`) consistent zijn met de gevonden patronen.

### Stap 5 — Aanbevelingen

Stel maximaal 3 concrete, meetbare aanpassingen voor. Formaat:

```
[AANBEVELING 1] Verhoog score_threshold van X naar Y
  Reden: winnaars hadden gemiddeld score Z, verliezers Z-0.1
  Verwacht effect: ~N trades/week minder, WR stijgt naar ~X%

[AANBEVELING 2] ...
```

Markeer duidelijk:
- Wat nu te tweaken is (drempelwaarden, SL pct, timeouts)
- Wat structureel anders moet (signaallogica, universe, richting)

### Stap 6 — Sla bevindingen op

Als er niet-voor-de-hand-liggende patronen zijn (exchange gedrag, signaal bias, onverwachte correlaties), stel een memory entry voor.

## Output formaat

Presenteer als één compact rapport:
1. **Samenvatting** (3 regels max): PnL, WR, PF
2. **Patroonanalyse tabel** winners vs losers
3. **Top 3 aanbevelingen** met verwacht effect
4. **Open posities status** (unrealized PnL, risico)
5. **Acties** — wat nu te deployen vs wat nader te onderzoeken

Houd het onder 400 woorden tenzij de analyse het vraagt.
