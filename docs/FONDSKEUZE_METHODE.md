# Fondskeuze binnen een thema — de methode en het bewijs

*Vastgelegd 2026-08-18, uit een lang gesprek waarin elke stap gemeten is in
plaats van beredeneerd. Gereedschap: `scripts/keten_overlap.py` (overlap met de
ketenschakel) en `scripts/thema_drukte.py` (waar staat het thema in zijn cyclus).*

## De vraag waar dit mee begon

Een willekeurig mandje aandelen verslaat de index niet: ~4% van de aandelen
levert álle netto vermogensgroei, de mediaan doet het slechter dan een
spaarrekening (Bessembinder). Het *gemiddelde* van een willekeurige selectie is
gelijk aan de index, de *mediaan* ligt eronder — je verliest waarschijnlijk, met
een kleine kans dat je enorm wint. Bij 20 namen domineert die scheefheid.

Thema's leken de tussenweg: geen losse namen, wel gerichte blootstelling. En
thema-ETF's leken de oplossing voor het stockpicking-risico bínnen een thema.

## De bevinding die alles omdraaide

**De spreiding BINNEN een thema is groter dan die tussen thema's.** Drie
onafhankelijke metingen, drie tijdshorizonnen, dezelfde richting:

| Thema | Venster | Spreiding | Winnaar | Verliezer |
|---|---|---|---|---|
| Robotics | 12 jaar | **426pp** | ARKQ (2014, breed) +338pp | BOTZ (2016) −88pp |
| Cloud/SaaS | 7 jaar | **129pp** | SKYY (2011, breed) +32pp | WCLD (2019, "emerging") −98pp |
| Space | 8 maanden | **57pp** | ROKT (2018, breed) +62% | NASA (mrt 2026, puur) +5% |

*(t.o.v. de wereldindex over hetzelfde venster)*

**Elke keer won het oudere, bredere fonds van het nieuwere, "zuiverdere".**

> ## ❌ TERUGGENOMEN 2026-08-18 — die regel houdt geen stand
>
> Bovenstaande drie gevallen zijn diezelfde dag getoetst over **79 fondsparen in
> 20 thema's** (`scripts/fondsregel_toets.py`). Uitslag:
>
> | eenheid | resultaat | afwijking van toeval |
> |---|---|---|
> | Per fondspaar | 49/79 = 62% | 2,14 standaardfouten |
> | **Per thema** *(de juiste eenheid)* | **11/18 = 61%** | **0,94 standaardfouten** |
>
> Paren binnen één thema delen fondsen en zijn dus **niet onafhankelijk**: wint SMH
> van drie andere fondsen, dan telt datzelfde fonds drie keer mee. Op themaniveau —
> één thema, één waarneming — blijft er 0,94 standaardfouten over. **Dat is niet van
> toeval te onderscheiden.**
>
> **Waarom de eerste drie gevallen misleidden.** In alle drie vergeleek ik het
> *oudste* fonds met het *nieuwste* — precies het paar waar het effect het grootst
> uitvalt. De volledige toets neemt óók de tussenliggende paren mee, en dan
> verdampt het. Een leerboek-selectie-effect, en ik heb het zelf gemaakt.
>
> Het scherpste tegenvoorbeeld komt uit robotics, één van mijn eigen "bevestigingen":
> **ROBO (2013) verloor 374,5pp van ARKQ (2014)** — het oudere fonds, zwaar
> verslagen. Ik had alleen het paar ARKQ-vs-BOTZ laten zien.
>
> **Wat wél overeind blijft — en waarom dat iets anders is:**
> - Ben-David e.a. gaat over fondsen die worden gelanceerd **in een piekend thema**,
>   niet over leeftijd in het algemeen. Dat is gepubliceerd en blijft staan.
> - De holdings-analyse (`scripts/keten_overlap.py`) rust op wat je **bezit**, niet
>   op een statistische regelmaat. Die staat los van deze uitslag.
> - WCLD en NASA blijven ware gevallen. Ze generaliseren alleen niet naar leeftijd.
>
> **Gebruik leeftijd dus niet als selectieregel.** Kijk naar het mandje en naar het
> moment van lancering ten opzichte van de aandacht voor het thema — niet naar de
> oprichtingsdatum op zich.

En er is een mechanisme, geen toeval: een nieuw fonds wordt gelanceerd wanneer
het thema al loopt. Het mist het eerste been per constructie en vangt de daling
wél. Bij space is dat exact zichtbaar — NASA kwam binnen op 30 maart 2026, ving
twee van de acht maanden stijging en alle daling.

Dat sluit aan op Ben-David, Franzoni, Kim & Moussawi (*Review of Financial
Studies*, 2023): gespecialiseerde ETF's blijven ~30% achter in hun eerste vijf
jaar, omdat aanbieders lanceren wanneer de aandacht piekt.

## Waar de waarde zit — en waar niet

| | grootte van de fout | wat het vraagt |
|---|---|---|
| Verkeerd fonds binnen een goed thema | **57 tot 426pp** | rekenwerk op openbare holdings |
| Te vroeg/te laat instappen | ~90pp (cloud) | een glazen bol |

Fondskeuze is **narekenbaar werk waarin je vandaag gelijk of ongelijk kunt
krijgen**. Themakeuze en timing zijn voorspellen. Steek de tijd in het eerste.

Je hebt geen voorsprong op het nieuws nodig — je hebt een voorsprong nodig op
iedereen die het etiket leest zonder het mandje te openen.

## Vier regels

**1.** ~~Voorkeur voor het oudere, bredere fonds.~~ **VERVALLEN** — getoetst op
79 paren en niet van toeval te onderscheiden. Zie het kader hierboven. In plaats
daarvan: **beoordeel op het mandje** (regel 4) en op het lanceermoment ten
opzichte van de aandachtspiek (regel 2), niet op leeftijd.

**2. Nooit een fonds waarvan de index voor het product is gemaakt.** EUDF
(WisdomTree Europe Defence, index gemaakt voor het fonds, gelanceerd 4 maart 2025
op de piek van het herbewapeningsverhaal) en NASA (maart 2026) zijn de
leerboekgevallen.

**3. Schrijf de uitstapvoorwaarde op vóór de aankoop.** WCLD werd gelanceerd twee
jaar vóór de piek — vroeg genoeg — en kostte alsnog 97pp omdat er niet verkocht
werd. Vasthouden gaf +61%, op de top verkopen +151%. **De instap was nooit het
probleem.**

**4. Controleer het mandje, niet het label.** Drie keer misgegaan:
- Slot 1: de tolhuisjes waren ~15% van het fonds, commodity-geheugen 22%
- QTUM ("Defiance Quantum", +417pp): ~3% écht quantum, de rest is Cloudflare,
  Snowflake, RTX, Microsoft, Airbus, Amazon van elk ~1,4%
- CPQ: 10,4% megacap die je in de kern al bezit — tegen 0,60% i.p.v. 0,07%

## Wanneer een thema-ETF structureel niet kán bestaan

Slot 3 (software-infrastructuur, tolhuisje = overstapkosten) bleef leeg, en de
reden generaliseert:

> Bedrijven **mét** overstapkosten zijn per definitie gevestigde grote namen. Die
> zitten al in je wereldindexfonds, én worden door thema-indices juist uitgesloten
> — want "pure play" en "emerging" is wat een thematisch fonds verkoopt.

**Een switching-cost-these en de productcategorie thema-ETF zijn structureel
onverenigbaar.** Is het tolhuisje daarentegen een *technologie* (EUV-lithografie,
de scherpste foundry-node), dan valt het wél samen met een sector en dus met een
ETF. Dat is waarom slot 1 kan en slot 3 niet.

**Toets vooraf:** is het tolhuisje een technologie of een klantrelatie? Bij het
eerste bestaat er een instrument, bij het tweede niet.

## De onprettige consequentie

Elke stap richting "zuiverdere thema-expressie" maakte het in élke meting
slechter. Doorgetrokken wijst die pijl naar de kern. Dat betekent niet dat
thema's niet werken — het betekent dat **de bewijslast bij de satelliet ligt en
niet bij het indexfonds**, en dat de satelliet klein hoort te blijven tot hij die
bewijslast heeft gedragen.

## Wat hier NIET uit volgt

"Koop bij een IPO-aankondiging in een thema." De space-reeks laat een perfect
buy-the-rumour-patroon zien (+31% vanaf de aankondiging terwijl de wereldindex
−4,6% deed; top op 27 mei, twee weken vóór de IPO van 12 juni). Maar dat is n=1.
Cannabis had exact dezelfde vorm en staat 93% onder de top. Op één geval een
instapregel bouwen is precies waar dit project al een keer aan onderdoor ging —
zie memory `feedback_systematic_alpha_hard`.


---

## Nawoord 2026-08-18: twee toetsen, twee keer niets

Na het terugnemen van de leeftijdsregel is ook het onderliggende **mechanisme**
getoetst — het enige dat de eerste toets overleefde. Ben-David e.a. zeggen dat
fondsen slecht presteren omdat ze worden gelanceerd wanneer een thema heet is.
Dat is vooruit af te lezen: op de dag van lancering zie je wat het thema de twee
jaar daarvoor deed.

`scripts/aanloop_toets.py`, 24 fondsen over 14 thema's, uitkomst gemeten over een
**vaste** periode van 36 maanden na lancering (relatief aan de wereldindex):

| | n | gemiddeld | spreiding |
|---|---|---|---|
| Rustige aanloop (gem. +8%) | 12 | −0,8pp | 74 |
| Hete aanloop (gem. +61%) | 12 | **−27,1pp** | 47 |
| verschil | | **+26,3pp** | **t = +1,04** |

Correlatie aanloop ↔ uitkomst: **−0,07** (t = −0,33).

De richting klopt en de orde van grootte komt overeen met Ben-David's −30% over
vijf jaar. Maar **de spreiding binnen elke groep is drie keer zo groot als het
verschil ertussen**. Met twaalf waarnemingen per groep is dit niet van toeval te
onderscheiden.

> ⚠️ **Ook hier zat eerst een definitiefout in.** De eerste versie mat het
> rendement *sinds lancering tot nu*, waardoor XSD (2006) twintig jaar
> samengestelde groei had en MSOS (2020) zes. Dat gaf een verschil van 430,7pp
> tussen de groepen. Met een vaste horizon blijft er 26,3pp over — de horizon
> deed bijna al het werk. **Vergelijk nooit rendementen over ongelijke periodes.**

### De echte conclusie van deze middag

Twee zelfbedachte thema-regels, twee keer getoetst, twee keer niets. En dat is
geen gebrek aan inspanning maar een **structureel gegeven**: er bestaan simpelweg
te weinig thema-ETF's met genoeg historie om regels over thema-ETF's te toetsen.
Bij 20 thema's en 24 bruikbare waarnemingen is elke uitkomst binnen de ruis.

**Wat daaruit volgt voor hoe we verder werken:**

1. **Bedenk geen eigen thema-regels meer om ze daarna te backtesten.** De data
   kan het antwoord niet dragen. Dit is dezelfde muur als in memory
   `feedback_systematic_alpha_hard`, nu in een andere assetklasse.
2. **Regels mogen komen uit gepubliceerd onderzoek op grote steekproeven**
   (Ben-David over lanceermoment, Bessembinder over scheefheid, de
   kostenliteratuur) — niet uit onze eigen 24 waarnemingen.
3. **Of uit logica over wat je bezít.** De mandanalyse
   (`scripts/keten_overlap.py`) is géén bewezen voorspeller van rendement, en dat
   moet zo genoemd worden. Het is een **controleerbare beschrijving van wat je
   koopt** — dat QTUM ~3% quantum is, blijft waar ongeacht wat de statistiek zegt.
   Die waarde staat los van voorspelkracht.

Het onderscheid tussen "beschrijving" en "voorspeller" is de belangrijkste
opbrengst van deze middag, en het is vandaag twee keer verschoven zonder dat
iemand het merkte.
