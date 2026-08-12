# Kritische review — verdient het gebouwde zijn plek?

Beoordeelt gedaan werk streng en met bewijs. **Niet** hetzelfde als `/review`, dat de documentatie en memory op actualiteit controleert. Deze skill vraagt of het werk zelf deugt.

## Arguments
`$ARGUMENTS` — optioneel: `sessie` (default, het werk van deze sessie), `alles` (het hele systeem), of een pad/onderwerp (`research/`, `de dip-koper`).

---

## De regel die deze skill draagt

**Elke bevinding rust op bewijs uit het draaiende systeem of uit data. Niet op een indruk.**

Zelfreview faalt op één manier: je leest je eigen werk, het ziet er logisch uit, en je concludeert dat het goed is. Daarom is elke stap hieronder een *meting* of een *tegenvraag*, nooit een oordeel achteraf. Kom je met een oordeel dat je niet kunt staven, schrap het of ga het halen.

**Een review zonder ongemakkelijke bevinding is vrijwel altijd een review die niet is uitgevoerd.** Als alles goed lijkt, heb je de verkeerde vragen gesteld — begin bij stap 5.

---

## Stap 1 — Wat is er gebouwd, en werkt het echt?

Inventariseer het werk (`git log`, gewijzigde bestanden). Voor elk onderdeel:

- **Draait het in productie?** Niet "is het gedeployd" maar: laat een waarneembaar spoor zien — een logregel, een veld in een statebestand, een getal dat beweegt. Compileren en HTTP 200 zijn géén bewijs; op 2026-08-12 passeerde een bug beide en legde de sleeve plat.
- **Is het ná uitrol geverifieerd, of alleen ervoor?**
- **Wat is er sinds de bouw mee gebeurd?** Nul aanroepen sinds de deploy is een bevinding.

## Stap 2 — Verdient het zijn plek?

Voor elk onderdeel, hard:

- **Wat kost het?** Rekentijd, geheugen, aandacht, onderhoud, kans op storing.
- **Wat levert het op?** In euro's als het kan. Zo niet: welke beslissing wordt er beter van?
- **Wat gaat er kapot als je het weghaalt?** Is het antwoord "niets merkbaars", dan hoort het op de kill-lijst.

Zet dit af tegen `project_product_economics`: dit product verliest geld. Een onderdeel dat noch geld oplevert, noch een beslissing verbetert, kost netto.

> ⚠️ **Maar het huidige kapitaal is een testbudget.** Het kostenpercentage is een artefact van de schaal en verdampt bij groei — zie `feedback_testbudget_niet_doorschieten_op_kosten`. Gebruik de kostenmeetlat om luie kosten op te ruimen, **niet** om te besluiten of een onderdeel mag bestaan. Vraag bij elke besparing: *blijft dit bedrag relevant bij 30× het kapitaal?* Zo niet, dan is het geen bevinding maar een afleiding.

## Stap 3 — Klopt het nog met het plan?

- Welke items uit `docs/PLAN_2026-08.md` zijn besloten maar **niet uitgevoerd**? Die gaan vóór nieuwbouw.
- Wat is er gebouwd dat **niet** in het plan staat? Drift is toegestaan, maar dan bewust en benoemd.
- Is er iets gebouwd omdat het plan het zei, terwijl de **data inmiddels iets anders zegt**? Het plan is een besluit uit het verleden, geen bewijs.

## Stap 4 — De bekende faalpatronen van dít project

Loop ze expliciet langs; ze komen terug:

| Patroon | Waar te kijken |
|---|---|
| **Definitiefout** — een getal dat een andere vraag beantwoordt | Elke nieuwe metriek: welke vraag stelt hij, uit welke bron? |
| **Stille nul** — onmeetbaar geteld als 0 | Elke berekening met een `except` die 0 teruggeeft |
| **Zelf-dichtslaande poort** — filters die alles gaan weigeren | Nieuwe drempels: kan dit ooit nog "ja" zeggen? |
| **State op twee plekken** | Nieuwe statebestanden: mounts én `STATE_FILES`? |
| **Gebouwd maar nooit gemeten** | Is er een meetlus die het oordeel kan weerleggen? |
| **Bevestigingszucht** | Is de nieuwe functie ooit tegen zichzelf getest? |

## Stap 5 — De tegenvragen

Stel ze letterlijk, en beantwoord ze met data:

1. **Wat zou waar moeten zijn om dit werk waardeloos te maken?** Onderzoek dat, in plaats van het te weerleggen.
2. **Welke bewering hier is nooit gemeten?**
3. **Wat is er gebouwd omdat het interessant was in plaats van omdat het nodig was?**
4. **Waar heb ik risico genomen (herstart, ingreep in productie) voor iets dat geen geld oplevert?**
5. **Als een buitenstaander alleen de cijfers zag — welke conclusie zou die trekken die wij vermijden?**

## Stap 6 — Rapporteer

```
## Kritische review — <datum>

### Werkt het
Per onderdeel: bewijs uit productie, of "niet geverifieerd".

### Verdient het zijn plek
Kosten tegen opbrengst. Expliciete kill-lijst.

### Drift
Wat er buiten het plan is gebouwd, en of dat bewust was.

### Wat ik fout deed
Concreet, met de correctie. Geen wollige zelfkritiek.

### Wat ik zou stoppen
Het onderdeel dat het minst verdient te blijven — mét reden.

### Eén ding dat nu telt
De hoogste hefboom, met bedrag of beslissing.
```

**Sluit af met de meest waardevolle openstaande beslissing**, niet met een samenvatting.

Let op het verschil met de *duurste*: die twee zijn zelden dezelfde. Een besparing is eenmalig en schaalt niet mee; een verbetering in selectie, allocatie of hoeveelheid kapitaal aan het werk groeit mee met het vermogen. 1 procentpunt rendement is op $3k dertig dollar en op €100k duizend euro — een besparing van $73 blijft $73. Eindigen op de kostenknop voelt scherp en is meestal de makkelijke uitweg.

---

## Hoe je dit verkeerd doet

- Een lijst maken van wat er af is. Dat is een statusupdate, geen review.
- Alleen kijken naar wat je zelf gebouwd hebt — kijk ook naar wat er al stond en niet meer nodig is.
- Zachte formuleringen ("kan wellicht beter"). Noem het onderdeel, het bedrag, het besluit.
- Concluderen dat alles klopt. Zie de regel bovenaan.
