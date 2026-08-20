# Thema — welke thema's doen ertoe, en in welke volgorde

Rangschikt thema's op **vastgelegd geld en structuur**, niet op verwachting. Levert een kaart per thema in `research/themes.json`.

> **Een thema-kaart is geen koopsignaal.** Een thema koop je nooit rechtstreeks. De kaart bepaalt of het thema **de trechter in gaat** — daarna beslist `scripts/keten_overlap.py` over het instrument en `/scorecard` over de losse namen. Drie aparte beslissingen, drie aparte documenten.

## Arguments

`$ARGUMENTS`

| Vorm | Betekenis |
|---|---|
| `<naam>` | analyseer één thema volledig |
| `rank` | rangschik alle thema's in `research/themes.json` |
| `verken` | lever kandidaat-thema's op uit de bronnen, nog niet scoren |
| *(leeg)* | vraag om een thema, of doe `verken` |

---

## De regel die deze skill draagt

**Weeg wat verifieerbaar is boven wat aannemelijk is.**

Op 2026-08-18 zijn twee zelfbedachte thema-regels getoetst en allebei verworpen (`docs/FONDSKEUZE_METHODE.md`). De conclusie was structureel: **er is te weinig data om regels over thema's te valideren** — bij ~24 bruikbare waarnemingen ligt elke uitkomst binnen de ruis. Verzin hier dus geen nieuwe regel om die later te backtesten; dat kan niet, en het is al twee keer geprobeerd.

Wat wél mag: gepubliceerd onderzoek op grote steekproeven, en **feiten over vastgelegd geld**. Een aangenomen begroting is geen voorspelling.

---

## Stap 0 — laad de context

1. `docs/FONDSKEUZE_METHODE.md` — wat er al weerlegd is, en waarom
2. `docs/CONVICTION_BARBELL_PLAN.md` par. 1b — het tolhuisje-criterium en de bestaande slots
3. `research/themes.json` — bestaat er al een kaart? (dan is dit een herziening)

## Stap 1 — de keten uitschrijven, vóór alles

Een thema is geen laag maar een keten. Schrijf de schakels op van grondstof tot eindklant, en **wijs aan welke schakel de prijs bepaalt en waarom niemand daaromheen kan.**

Zonder die stap is de rest onmogelijk: de poorten gaan over díé schakel, niet over het thema als geheel. "AI" heeft geen marge; chips, geheugen, stroom en modellen hebben elk hun eigen.

## Stap 2 — drie poorten (binair, dit is een stopmoment)

**Faalt er één → AFVALLER. Direct stoppen.**

### Poort 1 — is er geld vastgelegd?

Niet "verwachten analisten groei", maar: **stroomt er geld naartoe dat al besloten is?** In afnemende hardheid:

| Hardheid | Bron |
|---|---|
| **Hardst** | Aangenomen wetgeving of meerjarige overheidsbegroting (NAVO-verplichtingen, EU-programma's, CHIPS-achtige wetten) |
| Hard | Getekende orderportefeuille die bedrijven in hun jaarrekening rapporteren |
| Redelijk | Capex-verwachting die bedrijven zélf hebben afgegeven (hyperscalers, netbeheerders, nutsbedrijven) |
| **Telt niet** | Marktramingen, "TAM van $X biljoen in 2030", analistenkoersdoelen, persberichten |

Die laatste rij is geen strengheid maar een les: een marktraming is marketing van degene die het rapport verkoopt.

### Poort 2 — bestaat er een tolhuisje?

Is er in de keten een schakel met **prijszettingsmacht** waar niemand omheen kan? Is de hele keten een uitwisselbaar product met kapitaalintensieve productie — batterijen, zon, waterstof, generieke AI-mandjes — dan klopt het verhaal maar niet de economie. `CONVICTION_BARBELL_PLAN` sluit die expliciet uit.

**Toets erbij: is het tolhuisje een TECHNOLOGIE of een KLANTRELATIE?** Bij een technologie (EUV-lithografie, de scherpste foundry-node) valt het samen met een sector, en bestaat er dus een instrument. Bij een klantrelatie (overstapkosten, systems of record) niet — dat zijn gevestigde grote namen die thema-indices juist uitsluiten. Slot 3 bleef daarom leeg; zie `FONDSKEUZE_METHODE.md`.

### Poort 3 — bezit je het niet al?

Hoeveel van dit thema zit al in het wereldindexfonds? Is het thema in wezen megacap-tech, dan koop je tegen 0,40-0,60% wat je al voor 0,07% hebt. **Dat is geen blootstelling maar duurder gemaakte kern.**

## Stap 3 — vijf dimensies (`5..1`, plus `?` en `n.v.t.`)

**Eén zin met een getal en een bron per dimensie.** Geen getal = `?` = niet geanalyseerd, en `?` mag nooit als een 3 worden weggeschreven omdat het onhandig staat.

| # | Dimensie | 5 | 1 |
|---|---|---|---|
| 1 | **Hardheid van het geld** | wetgeving, meerjarig vastgelegd | analistenverwachting |
| 2 | **Aard van het tolhuisje** | technologie, dus koopbaar | klantrelatie, niet koopbaar |
| 3 | **Fase van de doorbraak** | draait op schaal, omzet groeit | lab of demo, geen omzet |
| 4 | **Drukte** *(contra)* | menigte weg, weinig fondsen | net gelanceerde fondsen, dicht bij de top |
| 5 | **Instrumenteerbaarheid** | mandje dekt de aangewezen schakel | alleen brede sectorbeta |

Dimensie 4 lees je af met `scripts/thema_drukte.py`, dimensie 5 met `scripts/keten_overlap.py`. **Niet schatten wat te meten valt.**

⚠️ **Dimensie 5 moet op een KOOPBAAR fonds gemeten worden.** De holdings die
gratis en programmatisch beschikbaar zijn, zijn bijna altijd die van een
Amerikaans fonds — en die kun je als Europese particulier niet kopen (PRIIPs,
geldt bij élke broker). Meten op de Amerikaanse tweeling mag om de keten te
begrijpen, maar noteer dan expliciet `instrument_koopbaar: false` en geef de
score pas een cijfer als de UCITS-variant is hermeten. Let op: de UCITS-versie
volgt vaak een *andere variant* van dezelfde index (bij GRID de
Exclusions-index), dus de overlap draagt niet over. Zie
`docs/FONDSKEUZE_METHODE.md` § "Wat je kunt meten is niet wat je kunt kopen".

⚠️ **Sentiment en media-aandacht zijn een CONTRA-indicator, geen plus.** Iedereen weet dat AI groot is; dat is de definitie van ingeprijsd. Hoge aandacht verlaagt dimensie 4 — hij verhoogt hem nooit.

## Stap 4 — rangschikken

**Rangschik primair op dimensie 1, de hardheid van het geld.** Dat is de enige dimensie die niets voorspelt en die daarom als enige stevig staat. De overige vier zijn schiftingscriteria, geen optelsom.

**Tel de dimensies niet op tot één cijfer.** Een gemiddelde suggereert een precisie die er niet is, en laat een zwakke poort verdwijnen in een mooi totaal. Rangschik, benoem waar het schuurt, klaar.

## Stap 5 — verdict

- **IN DE TRECHTER** — alle poorten PASS, dimensie 1 ≥ 3. Actie: holdings van een representatieve ETF toevoegen aan `UNIVERSUM` in `research/screen.py`, zodat de bestaande cadans er kandidaten uit haalt.
- **VOLGEN** — poorten PASS maar iets is zwak of onmeetbaar. **Wachtvoorwaarde verplicht:** welke gebeurtenis maakt dit "IN DE TRECHTER"? Een begroting die wordt aangenomen, een orderportefeuille die een drempel haalt, fondsuitgifte die opdroogt.
- **AFVALLER** — een poort faalt.

Er is bewust **geen KOOPBAAR**. Een thema wordt nooit gekocht; het levert kandidaten.

**Vóór het verdict opschrijven, niet erna:** wat zou dit thema laten vallen? Een niet-verlengde begroting, een gebroken knelpunt, omzet van de zuivere spelers die stagneert. Achteraf verzin je die naar de koers.

## Stap 6 — opleveren

Kaart in `research/themes.json`, met minimaal:

```
naam · geanalyseerd_op · keten[] · tolhuisje_schakel · tolhuisje_soort (technologie|klantrelatie)
poorten{vastgelegd_geld, tolhuisje, niet_al_in_kern}
scores{hardheid_geld, aard_tolhuisje, fase_doorbraak, drukte, instrumenteerbaarheid}
bronnen[]        <- per bedrag: welk document, welke datum, welk bedrag
verdict · these_breuk[] · wacht_voorwaarden[]
benchmark_prijs_bij_analyse   <- nooit null, zelfde reden als bij /scorecard
```

**`bronnen[]` mag geen samenvatting bevatten.** Per bedrag: het document, de datum en het bedrag zelf. Een thema-kaart zonder herleidbare bedragen is een mening met opmaak.

Sluit af met: het verdict · de hardste geldbron mét bedrag · wat er op `?` staat · de plaats in de rangschikking.

---

## Hoe je dit verkeerd doet

- **Een thema kiezen omdat het interessant is.** Dat is het altijd. De poorten gaan over geld en structuur, niet over of het boeiend is.
- **Marktramingen als bewijs gebruiken.** Zie poort 1, onderste rij.
- **Sentiment als plus lezen.** Zie stap 3.
- **Een thema-kaart als koopbesluit gebruiken.** Er zitten nog twee beslissingen tussen: welk instrument, en welke namen.
- **Een nieuwe regel bedenken om die later te backtesten.** Dat kan niet met deze data — twee keer geprobeerd op 2026-08-18, twee keer niets.
