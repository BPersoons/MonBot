# Boek een broker-order in

Verwerk een aankoop of verkoop bij DEGIRO in de administratie en op het dashboard.

## Waarom dit een skill is

DEGIRO heeft **geen API**. `config/broker_holdings.json` wordt daarom met de hand
bijgehouden en is **niet tegen de broker te verifiëren** — het bestand is precies zo waar
als de discipline waarmee het wordt bijgewerkt. Dat maakt dit het zwakste punt in de hele
meetketen, en het is de reden dat de stappen hieronder volledig moeten.

Twee van de vier stappen kun je stilzwijgend missen, en beide hebben dit project eerder
geld of tijd gekost: de host-kopie (die wint van de repo) en de vaste artifact-URL
(zonder die parameter ontstaat een tweede pagina die uit elkaar loopt).

## Wat je van de gebruiker nodig hebt

Vraag om het **bevestigingsscherm** van elke transactie, niet om losse getallen. Daarop
staat alles: aantal, koers, transactiekosten, **AutoFX** en de uitvoeringsplaats.

Ontbreekt AutoFX, vraag er dan naar. Bij een fonds met een vreemde share-class-valuta is
dat de enige manier om te weten of er 0,25% valutakosten zijn betaald. **Leid het niet
af** — zie `docs/FONDSKEUZE_METHODE.md`.

## Stappen — alle vier, in volgorde

### 1. `config/broker_holdings.json` bijwerken, op BEIDE plekken

Per positie: `aantal`, `gemiddelde_koers_eur`, `kostprijs_eur`, en een regel in
`_transacties` met datum, tijd, aantal, koers, kosten en beurs. Bij een verkoop óók
`gerealiseerd_eur`. Zet `laatst_bijgewerkt` op vandaag.

Gaat een order in tegen een vastgelegde regel, **schrijf de reden in de transactie**.
Over een half jaar is anders niet meer na te gaan waarom.

- **Repo:** `config/broker_holdings.json`
- **Host:** `/home/bartpersoons_gmail_com/config/broker_holdings.json` — dit bestand is
  volume-mounted en de **HOST-kopie wint van de image**. Alleen de repo bijwerken bereikt
  productie niet.

Schrijf **in-place** (`open(p,"w")`), nooit via rename — een single-file bind mount hangt
aan de inode. Via ssh met een base64-heredoc, anders loop je vast op quoting.

`kas_eur` uit de transacties afleiden mag, maar markeer het dan als afgeleid en vraag de
gebruiker het echte saldo te controleren.

### 2. NAV opnieuw meten en de snapshot ophalen

```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b \
  --command='sudo docker exec agent_trader_swarm python -m utils.nav'
```
Daarna `nav.json` uit de container naar `nav_snapshot.json` in de repo (gitignored).
Zonder verse snapshot toont de pagina oude vermogenscijfers terwijl de koersen wél live
zijn — misleidender dan helemaal geen cijfer.

### 3. Dashboard bouwen

```
python scripts/overzicht.py
```

Controleer de uitvoer: vermogen, aantal namen, en of het nieuwe potje erin staat.

### 4. Publiceren op de VASTE URL

`docs/overzicht_artifact.html` publiceren **met de `url`-parameter** uit
memory `reference_overzichtspagina`. Favicon 📊, stabiel houden.

Zonder die parameter mint een sessie die de artifact niet zelf publiceerde een **nieuwe**
URL, en dan heeft Bart twee pagina's die uit elkaar lopen.

## Daarna controleren

- Klopt de allocatie nog met het plan? De kern hoort op **40%**. Zakt hij eronder, meld
  dat en leg de herstelregel vast: de volgende storting gaat eerst naar de kern.
- Staat de status van een thema-slot nog op "nog niet gekocht" terwijl er geld in zit?
  De koppeling positie↔slot gaat op **ISIN**, niet op rol.
- De handgeschreven planlijsten (`STAPPEN`, `BESLISSINGEN` in `scripts/overzicht.py`)
  volgen niets vanzelf. Verandert er iets aan het plan, werk ze bij — ze verouderen
  stil en dat is op deze pagina al twee keer gebeurd.
