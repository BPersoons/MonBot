"""Bouwt één stakeholder-pagina: waar staat het geld, het plan en de analyses.

    python scripts/overzicht.py

Waarom dit bestaat: er waren drie dashboards (swarm op :8080, research/dashboard.html,
docs/masterplan_dashboard.html) en geen enkele beantwoordde de vragen die er toe doen —
hoe ver zijn we, waar wachten we op, welke bedrijven en waarom. Informatie hoort naar
de lezer toe te komen, niet opgehaald te worden.

Bronnen: nav_snapshot.json (van de VM), research/ledger.json, live koersen via yfinance,
en de planstatus hieronder. Die laatste is met de hand onderhouden — een plan is een
besluit, geen meting, en dat hoort zichtbaar te zijn.
"""

import io
import json
import os
import sys
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

WORTEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# De meetlat komt uit research/track.py, niet uit een eigen kopie. Die kopie
# bestond wel, en toen de benchmark op 2026-08-24 van URTH (USD) naar WEBN (EUR)
# ging, zou deze pagina een ander — en fout — getal zijn gaan tonen dan het
# grootboek: zonder valuta-omrekening landt de hele EUR/USD-beweging in het
# verschil naam-min-benchmark. Eén meetlat, één plek.
sys.path.insert(0, os.path.join(WORTEL, "research"))
import track  # noqa: E402

UIT = os.path.join(WORTEL, "docs", "overzicht.html")
ARTIFACT = os.path.join(WORTEL, "docs", "overzicht_artifact.html")
POORTDATUM = datetime(2027, 2, 10, tzinfo=timezone.utc)

# De zes dimensies in gewone taal. Zonder deze vertaling leest de pagina als de
# code i.p.v. als een oordeel — zie docs/NAMEN.md voor dezelfde regel.
DIMS = {
    "role_in_chain": "rol in de keten", "margin_and_direction": "marge",
    "competition": "concurrentie", "scalability": "schaalbaarheid",
    "execution": "uitvoering", "valuation": "waardering",
}


def _sterk_zwak(scores):
    """Wat is goed aan deze naam, en wat houdt hem tegen. Afgeleid uit de
    scores, niet met de hand geschreven — anders veroudert het stilletjes."""
    sterk = sorted((v, DIMS.get(k, k)) for k, v in scores.items() if v is not None and v >= 4)
    zwak = sorted((v, DIMS.get(k, k)) for k, v in scores.items() if v is not None and v <= 2)
    if not sterk:
        best = max(((v, DIMS.get(k, k)) for k, v in scores.items() if v is not None),
                   default=None)
        sterk = [best] if best else []
    return ([n for _v, n in reversed(sterk)][:2], [n for _v, n in zwak][:2])


def _cijferdatum(ticker):
    """Datum van de eerstvolgende kwartaalcijfers — het moment waarop een
    fundamentele wachtvoorwaarde überhaupt KAN omslaan."""
    try:
        import importlib.util
        pad = os.path.join(WORTEL, "research", "track.py")
        spec = importlib.util.spec_from_file_location("_tr", pad)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _cijferdatum._fn = mod.next_earnings
    except Exception:
        _cijferdatum._fn = lambda t: None
    return _cijferdatum._fn(ticker)

# ── Planstatus: met de hand onderhouden, want een plan is een besluit ──────────
STAPPEN = [
    ("Handelsbot uitgezet", "klaar",
     "score_threshold op 0,40 en de armed-gate bewust AAN gelaten — uitzetten zou hem "
     "juist loslaten.", "2026-08-10"),
    ("LLM-council uitgezet", "klaar",
     "623 aanroepen per dag voor kandidaten die de drempel nooit halen. Plan §5.",
     "2026-08-12"),
    ("Papieren scorekaarten", "klaar",
     "20 van 20 namen gescoord; de meting draait vanzelf in GitHub Actions.",
     "2026-08-11"),
    ("Kostenbasis verlagen", "loopt",
     "Container gebruikt 252-292 MiB, niet de 595 waar het plan mee rekende. e2-micro "
     "mag, ~$73/jaar. Lage prioriteit: dit is een testbudget, en $73 blijft $73 terwijl "
     "1 procentpunt rendement met het vermogen meegroeit.", "geen datum"),
    ("Wereldindexfonds gekocht", "klaar",
     "156 WEBN à €12,782 op Tradegate, €1 kosten, geen valutakosten. 43% van het "
     "vermogen. Gefinancierd met verse euro's van de bank — crypto en USDC bleven staan.",
     "2026-08-20"),
    ("Thema-slot 1 klaargezet", "loopt",
     "Stroom en net, GRID UCITS (IE000J80JTL1), ketenoverlap 74,4% hermeten op de "
     "koopbare variant, kernselectie bevestigd. Halfgeleiders is als slot geschrapt: "
     "die zit al in het wereldindexfonds. Gaat open bij €25k.", "wacht op kapitaal"),
    ("Poort: versla de wereldindex", "loopt",
     "20 namen gescoord met prijs én benchmarkprijs. Afrekenen rond 10 februari 2027.",
     "2027-02-10"),
]

BESLISSINGEN = [
    ("Welk fonds voor het defensie-slot?",
     "Slot 2 heeft wél een thema maar géén geldig instrument. EUDF staat in de config, "
     "maar de eigen fondskeuze-methode wijst hem bij naam af: de index is voor het "
     "product gemaakt en het fonds is gelanceerd op de piek van het herbewapenings"
     "verhaal. Geen haast — er gaat niets open vóór €25k."),
    ("Mag de divergentie-screen gaan blokkeren?",
     "Staat op observeren. Op de huidige, zeer kleine steekproef zou hij de twee best "
     "presterende posities hebben tegengehouden. Pas beslissen bij ≥10 gestempelde "
     "posities."),
    ("Mag de dip-koper meer geld inzetten?",
     "Hij staat vol (6 posities) met $151 kas stil, en tranche 2 is uitgezet — dat geld "
     "kan langs geen enkele route ingezet worden. Openzetten is nu NIET verstandig: "
     "gerealiseerd staat op −$5,16 en alle winst is nog ongerealiseerd. Opnieuw meten "
     "als er meer gesloten posities zijn."),
]


def _laad(pad, standaard=None):
    try:
        with io.open(os.path.join(WORTEL, pad), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return standaard


def _koersen(tickers):
    """Live koersen; ontbrekende blijven None — nooit als 0 tellen."""
    try:
        import yfinance as yf
        data = yf.download(list(tickers), period="5d", progress=False, auto_adjust=True)["Close"]
        uit = {}
        for t in tickers:
            try:
                s = data[t].dropna() if t in data.columns else None
                uit[t] = float(s.iloc[-1]) if s is not None and len(s) else None
            except Exception:
                uit[t] = None
        return uit
    except Exception:
        return {t: None for t in tickers}


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def bouw():
    nav = _laad("nav_snapshot.json", {})
    ledger = _laad("research/ledger.json", {"entries": []})
    themas = _laad("research/themes.json", {"kaarten": []}).get("kaarten", [])
    actief = [e for e in ledger.get("entries", []) if not e.get("superseded_by")]
    bench = track.bench_config(ledger)
    bench_t = bench["ticker"]

    nodig = [e["ticker"] for e in actief] + [bench_t]
    if bench["fx_ticker"]:
        nodig.append(bench["fx_ticker"])
    prijzen = _koersen(nodig)
    bench_nu = prijzen.get(bench_t)
    fx_nu = prijzen.get(bench["fx_ticker"]) if bench["fx_ticker"] else None

    rijen = []
    for e in actief:
        nu = prijzen.get(e["ticker"])
        p0 = e.get("price_at_score")
        # rend staat in de valuta van de BENCHMARK (euro's), nu en p0 in dollars.
        rend, bench_rend = track.returns_pct(e, nu, bench_nu, fx_nu, bench)
        rel = (rend - bench_rend) if rend is not None else None
        scores = [v for v in e["scores"].values() if v is not None]
        wp = e.get("wait_price_below")
        rijen.append({
            "t": e["ticker"], "naam": e.get("name", ""), "verdict": e["verdict"],
            "score": (sum(scores) / len(scores)) if scores else None,
            "onbekend": sum(1 for v in e["scores"].values() if v is None),
            "p0": p0, "nu": nu, "rend": rend, "rel": rel,
            "wacht": (e.get("wait_conditions") or [e.get("wait_price_note") or "—"])[0],
            "wp": wp,
            "afstand": ((wp / nu - 1) * 100) if (wp and nu) else None,
            "beslis": e.get("deciding_number", ""),
            "partial": bool(e.get("wait_price_is_partial")),
            "handmatig": bool(e.get("manual_only_conditions")),
            "fund": bool(e.get("wait_fundamental")),
            "sterk_zwak": _sterk_zwak(e["scores"]),
            "cijfers": None,
        })
    # Sorteren op score beantwoordt de verkeerde vraag. Wat je wil weten is: hoe
    # DICHT staat deze naam bij koopbaar. Daarom drie groepen, elk met een eigen
    # trigger-soort, en binnen groep 1 op afstand.
    for r in rijen:
        if r["verdict"] == "AFVALLER":
            r["groep"] = 3
        elif r["afstand"] is not None:
            r["groep"] = 1
        else:
            r["groep"] = 2
    for r in rijen:
        if r["groep"] == 2:
            r["cijfers"] = _cijferdatum(r["t"])
    rijen.sort(key=lambda r: (r["groep"],
                              -(r["afstand"] if r["afstand"] is not None else -999),
                              -(r["score"] or 0)))

    dagen = (POORTDATUM - datetime.now(timezone.utc)).days
    gemeten = [r["rel"] for r in rijen if r["rel"] is not None]
    gem_rel = sum(gemeten) / len(gemeten) if gemeten else 0.0
    geraakt = [r for r in rijen if r["afstand"] is not None and r["afstand"] >= 0]

    # ── tegels ────────────────────────────────────────────────────────────────
    tegels = [
        ("Vermogen", "$%s" % format(round(nav.get("totaal_usd", 0)), ",d").replace(",", "."),
         "compleet gemeten" if nav.get("compleet") else "ONVOLLEDIG — ondergrens", "neutraal"),
        ("Kostenhorde", "%.1f%%" % (160.0 / max(nav.get("totaal_usd", 0), 1) * 100),
         "$160/jaar infrastructuur — was 5,2% op $3.081, en dat cijfer daalt "
         "met elke euro erbij", "letop" if 160.0 / max(nav.get("totaal_usd", 1), 1) < 0.04 else "kritiek"),
        ("Namen gescoord", "%d / 20" % len(rijen), "poort-eis gehaald", "goed"),
        ("Wachtvoorwaarde geraakt", str(len(geraakt)),
         ", ".join(r["t"] for r in geraakt) if geraakt else "vandaag koop je niets", "neutraal"),
    ]
    tegels_html = "".join(
        '<div class="tegel"><div class="tegel-kop">%s</div>'
        '<div class="tegel-getal t-%s">%s</div><div class="tegel-sub">%s</div></div>'
        % (_esc(k), toon, _esc(v), _esc(s)) for k, v, s, toon in tegels)

    # ── potjes ────────────────────────────────────────────────────────────────
    potjes_html = ""
    for p in nav.get("potjes", []):
        if p.get("status") != "ok" or not p.get("waarde_usd"):
            continue
        aandeel = p.get("aandeel_pct", 0)
        potjes_html += (
            '<div class="potje"><div class="potje-rij">'
            '<span class="potje-naam">%s</span>'
            '<span class="potje-waarde">$%s <span class="potje-pct">%.1f%%</span></span></div>'
            '<div class="balk"><div class="balk-vul" style="width:%.1f%%"></div></div>'
            '<div class="potje-detail">%s</div></div>'
            % (_esc(p["label"]), format(round(p["waarde_usd"]), ",d").replace(",", "."),
               aandeel, aandeel, _esc(p.get("detail", ""))))

    # ── stappen ───────────────────────────────────────────────────────────────
    stappen_html = ""
    for naam, staat, uitleg, wanneer in STAPPEN:
        stappen_html += (
            '<div class="stap s-%s"><div class="stap-kop">'
            '<span class="stap-naam">%s</span><span class="pil p-%s">%s</span></div>'
            '<p class="stap-uitleg">%s</p>'
            '<div class="stap-wanneer">%s</div></div>'
            % (staat, _esc(naam), staat, _esc(staat), _esc(uitleg), _esc(wanneer)))

    # ── namen ─────────────────────────────────────────────────────────────────
    KOPPEN = {
        1: ("Kan koopbaar worden door een koersdaling",
            "Deze namen hebben een vooraf vastgelegde koopprijs. Zakt de koers daarheen, "
            "dan mag je kopen — mits het oordeel op de dan geldende cijfers standhoudt."),
        2: ("Wacht alleen op betere cijfers",
            "Geen koopprijs; deze namen worden pas interessant als de bedrijfscijfers "
            "verbeteren. Het eerstvolgende moment waarop dat kán blijken staat erbij."),
        3: ("Afgevallen",
            "Een poort faalde. Deze staan er alleen nog om het oordeel toetsbaar te houden."),
    }
    tr = ""
    vorige = None
    for r in rijen:
        if r["groep"] != vorige:
            kop, uitleg = KOPPEN[r["groep"]]
            tr += ('<tr class="groepkop"><td colspan="5"><strong>%s</strong>'
                   '<div class="groepuitleg">%s</div></td></tr>' % (_esc(kop), _esc(uitleg)))
            vorige = r["groep"]

        sterk, zwak = r["sterk_zwak"]
        waarom = '<span class="op">%s</span>' % _esc(" + ".join(sterk)) if sterk else "—"
        if zwak:
            waarom += ' <span class="zacht">· zwak: %s</span>' % _esc(", ".join(zwak))

        if r["groep"] == 3:
            wacht, nog, wanneer = '<span class="zacht">—</span>', "—", "—"
        elif r["afstand"] is not None:
            if r["afstand"] >= 0:
                wacht = '<span class="geraakt">$%.0f — GERAAKT</span>' % r["wp"]
                nog = '<span class="geraakt">nu</span>'
            else:
                wacht = "onder $%.0f" % r["wp"]
                nog = '<strong>%.0f%%</strong>' % abs(r["afstand"])
            if r["partial"]:
                wacht += ' <span class="zacht">(halve voorwaarde — geen koopsignaal alleen)</span>'
            wanneer = '<span class="zacht">zodra de markt daalt</span>'
        else:
            wacht = '<span class="zacht">%s</span>' % _esc(r["wacht"][:70])
            nog = "—"
            wanneer = _esc(r["cijfers"] or "?")
        if r["handmatig"]:
            wacht += ' <span class="zacht">· deels handmatig</span>'

        tr += ('<tr><td class="tk">%s<div class="volnaam">%s</div>'
               '<div class="zacht">$%s · %s</div></td>'
               '<td>%s</td><td>%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
               % (_esc(r["t"]), _esc(r["naam"][:28]),
                  ("%.2f" % r["nu"]) if r["nu"] else "—",
                  ("score %.1f" % r["score"]) if r["score"] else "niet gescoord",
                  waarom, wacht, nog, wanneer))

    beslis_html = "".join(
        '<div class="beslis"><div class="beslis-vraag">%s</div>'
        '<p class="beslis-uitleg">%s</p></div>' % (_esc(v), _esc(u))
        for v, u in BESLISSINGEN)

    # ── thema's ───────────────────────────────────────────────────────────────
    # Boven de namen, want dat is de volgorde van de hiërarchie: een thema levert
    # kandidaten, het is nooit zelf een koopbeslissing. Gerangschikt op SLOT —
    # dat is de vraag die je stelt ("waar gaat het geld heen"), niet op verdict.
    barbell = _laad("config/barbell_targets.json", {"themes": {}}).get("themes", {})
    broker = _laad("config/broker_holdings.json", {"posities": []}).get("posities", [])
    # Matchen op ISIN, niet op rol: de positie heeft rol "thema" terwijl de slot-
    # sleutel "NET" heet, en dan vindt de lookup niets terwijl er wel geld in zit.
    bezit_isins = {p.get("isin") for p in broker if (p.get("aantal") or 0) > 0}

    def _status(kaart):
        """Wat is de STAND van dit thema: staat er geld in, ligt het klaar, of niet?"""
        sleutel = kaart.get("barbell_slot")
        slot = barbell.get(sleutel) if sleutel else None
        if slot and slot.get("isin") in bezit_isins:
            return ("POSITIE", "goed", 0, slot)
        if slot and slot.get("testpositie"):
            return ("TESTPOSITIE KLAAR", "goed", 1, slot)
        if slot and slot.get("actief") is False:
            return ("GESCHRAPT ALS SLOT", "kritiek", 8, slot)
        if slot and slot.get("slot_order"):
            return ("SLOT %d · WACHT OP KAPITAAL" % slot["slot_order"], "neutraal",
                    1 + slot["slot_order"], slot)
        return ("GEEN SLOT", "neutraal", 7, None)

    verrijkt = []
    for k in themas:
        label, klasse, orde, slot = _status(k)
        verrijkt.append((orde, -(k.get("scores", {}).get("hardheid_geld") or 0), k, label, klasse, slot))
    verrijkt.sort(key=lambda x: (x[0], x[1]))

    tk = []
    for _o, _h, k, label, klasse, slot in verrijkt:
        sc = k.get("scores", {})
        hardste = (k.get("bronnen") or [{}])[0]
        balk = "".join(
            '<span class="dim"><b>%s</b><i>%s</i></span>' % (_esc(lab), sc.get(sl) or "?")
            for lab, sl in [("geld", "hardheid_geld"), ("tolhuisje", "aard_tolhuisje"),
                            ("fase", "fase_doorbraak"), ("drukte", "drukte"),
                            ("instrument", "instrumenteerbaarheid")])

        # Het instrument is een APARTE vraag van het thema — dat onderscheid is in
        # dit project al een keer misgegaan, dus het staat er expliciet bij.
        inst = k.get("instrument") or {}
        tw = inst.get("ucits_tweeling") or {}
        # VOLGORDE: een afgewezen fonds wint van een ingevuld slot. Anders leest de
        # pagina alsof defensie een instrument heeft, terwijl regel 2 EUDF bij naam
        # afwijst — en dan draagt het dashboard een bewering die het plan tegenspreekt.
        if tw.get("status", "").startswith("AFGEWEZEN"):
            fonds = ('<span class="neer">geen geldig fonds</span> — %s staat in de config '
                     'maar is afgewezen op regel 2 (index voor het product gemaakt, '
                     'gelanceerd op de piek)' % _esc(slot.get("ticker", "?") if slot else "?"))
        elif slot and slot.get("actief") is False:
            fonds = ('<span class="zacht">%s — niet meer in gebruik; dit slot is geschrapt</span>'
                     % _esc(slot.get("ticker", "?")))
        elif slot and slot.get("isin"):
            fonds = "%s · %s · %.2f%%/jr" % (_esc(slot.get("ticker", "?")),
                                             _esc(slot["isin"]), slot.get("ter_pct", 0))
            if tw.get("overlap_hermeten"):
                fonds += ' · <span class="op">ketenoverlap %.1f%%</span>' % tw.get("overlap_pct", 0)
            elif tw.get("isin"):
                fonds += ' · <span class="zacht">overlap nog niet hermeten</span>'
        else:
            fonds = '<span class="zacht">geen koopbaar fonds aangewezen</span>'

        test = ""
        if slot and slot.get("testpositie"):
            t = slot["testpositie"]
            test = ('<p class="thema-test"><strong>Testpositie — %s</strong><br>'
                    'Instap: geen timingregel, bewust. Verkoop: geen koersstop, alleen these-breuk. '
                    'Dit opent het thema-potje NIET; dat blijft op €25k.<br>'
                    '<strong>Testuitslag:</strong> geen AutoFX — de regel noteert in EUR op '
                    "Tradegate, ook al heet de share class 'A USD'. De naam van de share class "
                    'zegt niets over de noteringsvaluta.</p>'
                    % _esc(t.get("status", "")))

        tk.append(
            '<div class="thema">'
            '<div class="thema-kop"><h3>%s</h3><span class="pil %s">%s</span></div>'
            '<p class="thema-geld"><b>%s</b> — %s <span class="bron">(%s, %s)</span></p>'
            '<p class="thema-tol">Tolhuisje: <b>%s</b> · %s</p>'
            '<div class="dims">%s</div>'
            '<p class="thema-fonds">Fonds: %s</p>'
            '%s'
            '<p class="thema-actie">%s</p></div>'
            % (_esc(k.get("naam", "?")), klasse, _esc(label),
               _esc(hardste.get("bedrag", "?")), _esc(hardste.get("wat", "")),
               _esc(hardste.get("bron", "")), _esc(hardste.get("datum", "")),
               _esc(k.get("tolhuisje_schakel", "?")), _esc(k.get("tolhuisje_soort", "")),
               balk, fonds, test,
               _esc(k.get("actie") or (k.get("wacht_voorwaarden") or ["—"])[0])))
    themas_html = "".join(tk) or '<p class="leeg">Nog geen thema-kaarten.</p>'

    html = SJABLOON
    for sleutel, waarde in [
        ("BIJGEWERKT", datetime.now(timezone.utc).strftime("%-d %B %Y, %H:%M UTC")
         if os.name != "nt" else datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M UTC")),
        ("TEGELS", tegels_html), ("POTJES", potjes_html), ("STAPPEN", stappen_html),
        ("RIJEN", tr), ("BESLISSINGEN", beslis_html), ("THEMAS", themas_html),
        ("DAGEN", str(max(dagen, 0))),
        ("GEMREL", "%+.2f%%" % gem_rel), ("NAANTAL", str(len(gemeten))),
        ("BENCH", _esc("%s (%s, in %s)"
                       % (bench["label"], bench["name"], bench["currency"]))),
    ]:
        html = html.replace("{{%s}}" % sleutel, waarde)

    os.makedirs(os.path.dirname(UIT), exist_ok=True)
    with io.open(UIT, "w", encoding="utf-8") as fh:
        fh.write(html)

    # Artifact-variant: de publicatie wikkelt de inhoud zelf in doctype/head/body,
    # dus die schil moet eruit. <title> en <style> blijven — die worden gehesen.
    kern = html.split("<head>", 1)[1].replace("</head>", "").replace("<body>", "")
    kern = kern.rsplit("</body>", 1)[0]
    kern = "\n".join(r for r in kern.split("\n")
                     if not r.strip().startswith("<meta"))
    with io.open(ARTIFACT, "w", encoding="utf-8") as fh:
        fh.write(kern.strip() + "\n")

    print("Geschreven: %s" % UIT)
    print("           %s (voor publicatie)" % ARTIFACT)
    print("  vermogen $%.2f · %d namen · %d dagen tot de poort · %d trigger(s) geraakt"
          % (nav.get("totaal_usd", 0), len(rijen), max(dagen, 0), len(geraakt)))


SJABLOON = r"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Overzicht — vermogen, plan en analyses</title>
<style>
:root{
  color-scheme: light;
  --papier:#f6f6f4; --veld:#fffffe; --inkt:#14181c; --inkt2:#4a5560; --zacht:#7b858e;
  --lijn:#e2e3e0; --rand:rgba(20,24,28,.10);
  --accent:#1f6b66; --accent-zacht:#e6efee;
  --goed:#0ca30c; --letop:#b07d05; --kritiek:#d03b3b;
  --op:#1f6b66; --neer:#d03b3b;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --papier:#101418; --veld:#171d22; --inkt:#eef1f3; --inkt2:#aab4bd; --zacht:#7d8892;
  --lijn:#242c33; --rand:rgba(238,241,243,.10);
  --accent:#5fb3ad; --accent-zacht:#172a29;
  --goed:#3fbf3f; --letop:#e0a92a; --kritiek:#e26a6a;
  --op:#5fb3ad; --neer:#e26a6a;
}}
:root[data-theme="dark"]{
  --papier:#101418; --veld:#171d22; --inkt:#eef1f3; --inkt2:#aab4bd; --zacht:#7d8892;
  --lijn:#242c33; --rand:rgba(238,241,243,.10);
  --accent:#5fb3ad; --accent-zacht:#172a29;
  --goed:#3fbf3f; --letop:#e0a92a; --kritiek:#e26a6a;
  --op:#5fb3ad; --neer:#e26a6a;
}
*{box-sizing:border-box}
body{margin:0;background:var(--papier);color:var(--inkt);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
  padding:44px 20px 90px;-webkit-font-smoothing:antialiased}
.wrap{max-width:68rem;margin:0 auto}
h1{font-family:Georgia,"Iowan Old Style","Times New Roman",serif;font-weight:normal;
  font-size:2.05rem;line-height:1.2;margin:0 0 .35rem;text-wrap:balance;letter-spacing:-.01em}
h2{font-family:Georgia,"Iowan Old Style",serif;font-weight:normal;font-size:1.3rem;
  margin:0 0 .2rem;text-wrap:balance}
.sectie{margin-top:3.4rem}
.sectie-intro{color:var(--inkt2);font-size:.95rem;margin:0 0 1.1rem;max-width:62ch}
.dek{color:var(--inkt2);margin:0 0 .2rem;max-width:64ch}
.stempel{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-size:.75rem;
  color:var(--zacht);letter-spacing:.06em;text-transform:uppercase;margin-top:.9rem}
.tegels{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;
  margin-top:1.8rem}
.tegel{background:var(--veld);border:1px solid var(--rand);border-radius:3px;padding:15px 17px}
.tegel-kop{font-size:.7rem;text-transform:uppercase;letter-spacing:.09em;color:var(--zacht)}
.tegel-getal{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-size:1.85rem;
  margin:.3rem 0 .15rem;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.t-goed{color:var(--goed)} .t-kritiek{color:var(--kritiek)} .t-neutraal{color:var(--inkt)} .t-letop{color:var(--letop)}
.tegel-sub{font-size:.8rem;color:var(--inkt2);line-height:1.4}
.paneel{background:var(--veld);border:1px solid var(--rand);border-radius:3px;padding:20px 22px}
.potje{margin-bottom:1.15rem}
.potje:last-child{margin-bottom:0}
.potje-rij{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.potje-naam{font-size:.95rem}
.potje-waarde{font-family:ui-monospace,Consolas,monospace;font-variant-numeric:tabular-nums}
.potje-pct{color:var(--zacht);font-size:.8rem;margin-left:.4rem}
.balk{height:5px;background:var(--lijn);border-radius:2px;margin:.45rem 0 .3rem;overflow:hidden}
.balk-vul{height:100%;background:var(--accent);border-radius:2px}
.potje-detail{font-size:.78rem;color:var(--zacht)}
.stappen{display:flex;flex-direction:column;gap:2px}
.stap{background:var(--veld);border:1px solid var(--rand);border-left:3px solid var(--lijn);
  padding:14px 18px}
.stap.s-klaar{border-left-color:var(--goed)}
.stap.s-loopt{border-left-color:var(--letop)}
.stap.s-geblokkeerd{border-left-color:var(--kritiek)}
.stap-kop{display:flex;justify-content:space-between;align-items:center;gap:12px}
.stap-naam{font-weight:600;font-size:.98rem}
.stap-uitleg{margin:.4rem 0 .3rem;font-size:.9rem;color:var(--inkt2);max-width:66ch}
.stap-wanneer{font-family:ui-monospace,Consolas,monospace;font-size:.74rem;color:var(--zacht)}
.pil{font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;padding:2px 9px;
  border-radius:20px;border:1px solid var(--rand);white-space:nowrap}
.p-klaar{color:var(--goed)} .p-loopt{color:var(--letop)} .p-geblokkeerd{color:var(--kritiek)}
.v-koopbaar{color:var(--goed)} .v-volgen{color:var(--inkt2)} .v-afvaller{color:var(--kritiek)}
.pil.goed{color:var(--goed)} .pil.neutraal{color:var(--letop)} .pil.kritiek{color:var(--kritiek)}
.themas{display:grid;gap:14px}
.thema{border:1px solid var(--rand);border-radius:10px;padding:14px 16px;background:var(--veld)}
.thema-kop{display:flex;justify-content:space-between;align-items:center;gap:12px}
.thema-kop h3{margin:0;font-size:1.02rem;font-weight:650}
.thema-geld{margin:.55rem 0 .2rem;font-size:.92rem}
.thema-geld b{font-family:ui-monospace,Consolas,monospace}
.thema-geld .bron{color:var(--zacht);font-size:.78rem}
.thema-tol{margin:.1rem 0 .7rem;font-size:.88rem;color:var(--inkt2)}
.dims{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:.6rem}
.dim{display:flex;align-items:baseline;gap:6px;border:1px solid var(--rand);
  border-radius:6px;padding:3px 9px;font-size:.76rem}
.dim b{font-weight:500;color:var(--inkt2)}
.dim i{font-style:normal;font-family:ui-monospace,Consolas,monospace;font-weight:650}
.thema-actie{margin:0;font-size:.85rem;color:var(--inkt2);border-left:2px solid var(--rand);
  padding-left:10px}
.thema-fonds{margin:.1rem 0 .6rem;font-size:.84rem;color:var(--inkt2)}
.thema-test{margin:.2rem 0 .7rem;font-size:.84rem;color:var(--inkt2);background:var(--accent-zacht);
  border-radius:6px;padding:9px 12px}
.nu{background:var(--veld);border:1px solid var(--rand);border-left:3px solid var(--accent);
  border-radius:3px;padding:16px 20px;margin-top:1.6rem}
.nu h2{font-size:1.08rem;margin:0 0 .5rem}
.nu ol{margin:0;padding-left:1.25rem}
.nu li{margin-bottom:.4rem;font-size:.92rem;color:var(--inkt2)}
.nu li strong{color:var(--inkt)}
.leeg{color:var(--zacht);font-size:.9rem}
.scroll{overflow-x:auto}
.groepkop td{padding-top:22px;padding-bottom:6px;border-bottom:2px solid currentColor;opacity:.95}.groepkop strong{font-size:15px}.groepuitleg{font-weight:400;opacity:.62;font-size:12.5px;margin-top:3px;max-width:70ch}
  table{width:100%;border-collapse:collapse;font-size:.86rem;min-width:760px}
th{text-align:left;font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--zacht);font-weight:600;padding:0 10px 9px;border-bottom:1px solid var(--lijn)}
th.num,td.num{text-align:right;font-family:ui-monospace,Consolas,monospace;
  font-variant-numeric:tabular-nums}
td{padding:10px;border-bottom:1px solid var(--lijn);vertical-align:top}
tr:last-child td{border-bottom:none}
.tk{font-weight:600}
.volnaam{font-weight:normal;font-size:.74rem;color:var(--zacht);margin-top:1px}
.op{color:var(--op)} .neer{color:var(--neer)}
.zacht{color:var(--zacht);font-size:.8rem}
.geraakt{color:var(--letop);font-weight:600;font-size:.8rem}
.vraag{color:var(--letop);font-size:.72rem}
.beslis{background:var(--veld);border:1px solid var(--rand);border-radius:3px;
  padding:15px 18px;margin-bottom:10px}
.beslis-vraag{font-weight:600;font-size:.98rem}
.beslis-uitleg{margin:.35rem 0 0;font-size:.88rem;color:var(--inkt2);max-width:66ch}
.noot{border-left:2px solid var(--accent);padding:2px 0 2px 16px;margin-top:1.2rem;
  font-size:.88rem;color:var(--inkt2);max-width:66ch}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="wrap">

<h1>Waar we staan</h1>
<p class="dek">Vermogen, plan en analyses op één pagina — zodat je er niet naar hoeft te vragen.</p>
<div class="stempel">Bijgewerkt {{BIJGEWERKT}}</div>

<div class="tegels">{{TEGELS}}</div>

<div class="nu">
  <h2>Wat nu telt</h2>
  <ol>
    <li><strong>Inleg.</strong> Eén procentpunt rendement is $54; de vaste kosten zijn $160 per
    jaar. Elke euro erbij verlaagt de horde en doet meer dan elke analyse die er nog ligt.</li>
    <li><strong>Je kern staat onder doel.</strong> De testpositie is gefinancierd door 20 WEBN
    te verkopen, dus de kern zakte van 43% naar 37%. Dat ging in tegen de eigen regel
    (<em>"gefinancierd uit het veilige potje, niet uit de kern-ETF"</em>). Regel voor de
    volgende storting: <strong>eerst WEBN terug naar 40%</strong>, daarna pas iets anders.</li>
    <li><strong>De rest wacht op iets buiten ons:</strong> de twintig namen op kwartaalcijfers
    (eind oktober), de thema-slots op €25k, de poort op februari 2027.</li>
  </ol>
</div>

<div class="sectie">
  <h2>Waar het geld staat</h2>
  <p class="sectie-intro">Sinds 20 augustus staat het grootste deel niet meer in crypto:
  het wereldindexfonds is 43% en Aave 44%. Het broker-potje wordt <strong>met de hand
  bijgehouden</strong> — DeGiro heeft geen API, dus er is geen manier om het tegen de
  broker te controleren. Lukt de koersuitlezing niet, dan meldt de meting zichzelf als
  ONVOLLEDIG in plaats van stil een te laag totaal te geven.</p>
  <div class="paneel">{{POTJES}}</div>
</div>

<div class="sectie">
  <h2>Het plan</h2>
  <p class="sectie-intro">Zes stappen. Drie klaar, twee lopen, één zit vast.</p>
  <div class="stappen">{{STAPPEN}}</div>
  <div class="noot"><strong>De blokkade is weg.</strong> Tot 20 augustus stond 40% van
  het plan op nul omdat er geen route van USDC naar euro's was. Die vraag bleek al
  beslist: <strong>twee potjes naast elkaar</strong> — crypto en USDC blijven staan,
  DeGiro wordt gevuld met verse euro's van de bank. Geen omwisseling, geen extra
  rekening, geen onomkeerbaar netwerk-risico. Wat overbleef was het paspoort, en dat is
  opgelost. <strong>Wat nu telt is inleg:</strong> 1 procentpunt rendement is $54, de
  vaste kosten zijn $160 per jaar. Elke euro erbij doet meer dan elke analyse.</div>
</div>

<div class="sectie">
  <h2>Thema's</h2>
  <p class="sectie-intro">Gerangschikt op <strong>waar het geld heen gaat</strong>: eerst wat
  een positie heeft of klaarstaat, dan de slots die op kapitaal wachten, dan de rest. De
  volgorde van de slots volgt de kaarten hieronder — hardheid van het geld weegt het zwaarst,
  want dat is de enige dimensie die niets voorspelt.</p>
  <p class="sectie-intro">Twee dingen die je uit elkaar moet houden. Een <strong>thema</strong>
  is nooit zelf een koopbeslissing — het levert kandidaten voor de namen hieronder. Het
  <strong>fonds</strong> is daarna een aparte vraag, en die is twee keer anders uitgevallen dan
  het thema deed vermoeden. De vijf cijfers zijn 1-5, waarbij <em>drukte</em> omgekeerd werkt:
  hoog betekent dat de menigte weg is, dus laag is een waarschuwing.</p>
  <div class="themas">{{THEMAS}}</div>
</div>

<div class="sectie">
  <h2>De twintig namen</h2>
  <p class="sectie-intro">Gesorteerd op <strong>hoe dicht een naam bij koopbaar staat</strong>,
  niet op score — dat laatste beantwoordt de verkeerde vraag. Vandaag is er niets koopbaar,
  en dat komt niet door de kalender maar doordat geen enkele wachtvoorwaarde geraakt is.
  De poort van februari beslist of het selectie-potje opengaat en mag meegroeien; hij is
  <strong>geen koopverbod</strong> tot die tijd.</p>
  <p class="sectie-intro">Gemeten tegen {{BENCH}}: <strong>{{GEMREL}}</strong> over
  {{NAANTAL}} namen — na een handvol dagen is dat ruis, geen uitkomst. Afrekenen over
  {{DAGEN}} dagen.</p>
  <div class="paneel scroll"><table>
    <thead><tr><th>Naam</th><th>Waarom</th><th>Waar we op wachten</th>
    <th class="num">Nog</th><th class="num">Wanneer</th></tr></thead>
    <tbody>{{RIJEN}}</tbody></table></div>
  <p class="sectie-intro" style="margin-top:14px">Kopen vraagt zes voorwaarden tegelijk, vooraf
  vastgelegd: een wachtvoorwaarde geraakt · bij een halve voorwaarde ook de handmatige helft
  gecontroleerd · verdict opnieuw KOOPBAAR op de dán geldende cijfers · één positie van ~10% ·
  betaald uit het veilige potje, niet uit de index · these-breuk-regels vanaf dag één.</p>
</div>

<div class="sectie">
  <h2>Waar we op wachten</h2>
  <p class="sectie-intro">Drie beslissingen liggen bij jou. Zolang die openstaan, verandert
  er niets.</p>
  {{BESLISSINGEN}}
</div>

</div></body></html>"""


if __name__ == "__main__":
    bouw()
