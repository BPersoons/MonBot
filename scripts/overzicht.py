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
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

WORTEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UIT = os.path.join(WORTEL, "docs", "overzicht.html")
ARTIFACT = os.path.join(WORTEL, "docs", "overzicht_artifact.html")
POORTDATUM = datetime(2027, 2, 10, tzinfo=timezone.utc)

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
     "Container gebruikt 252-292 MiB, niet de 595 waar het plan mee rekende. "
     "24-uursmeting loopt; e2-micro scheelt ~$80/jaar.", "meting tot 2026-08-13"),
    ("Wereldindexfonds kopen", "geblokkeerd",
     "40% van het plan staat op nul. Er is geen route van USDC naar euro's — geen "
     "exchange-rekening, en geen enkel onderdeel van dit systeem kan euro's uitbetalen.",
     "wacht op een keuze"),
    ("Poort: versla de wereldindex", "loopt",
     "20 namen gescoord met prijs én benchmarkprijs. Afrekenen rond 10 februari 2027.",
     "2027-02-10"),
]

BESLISSINGEN = [
    ("Bij welke exchange stap je uit naar euro's?",
     "Zonder dit blijven het wereldindexfonds én de thema-ETF's staan — van die laatste "
     "zijn de ISIN's al gekozen maar is nooit iets gekocht. Advies: Bitvavo (euro's als "
     "basisvaluta, SEPA gratis)."),
    ("Mag de divergentie-screen gaan blokkeren?",
     "Staat op observeren. Op de huidige, zeer kleine steekproef zou hij de twee best "
     "presterende posities hebben tegengehouden. Pas beslissen bij ≥10 gestempelde "
     "posities."),
    ("Migreren naar een kleinere VM?",
     "Beslissend voor de kostenhorde: ~$80/jaar is 2,6 procentpunt. Wacht op de "
     "24-uursmeting."),
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
    bench_t = (ledger.get("_benchmark") or {}).get("ticker", "URTH")

    prijzen = _koersen([e["ticker"] for e in actief] + [bench_t])
    bench_nu = prijzen.get(bench_t)

    rijen = []
    for e in actief:
        nu = prijzen.get(e["ticker"])
        p0, b0 = e.get("price_at_score"), e.get("benchmark_price_at_score")
        rend = rel = None
        if nu and p0:
            rend = (nu / p0 - 1) * 100
            if bench_nu and b0:
                rel = rend - (bench_nu / b0 - 1) * 100
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
        })
    rijen.sort(key=lambda r: ({"KOOPBAAR": 0, "VOLGEN": 1, "AFVALLER": 2}[r["verdict"]],
                              -(r["score"] or 0)))

    dagen = (POORTDATUM - datetime.now(timezone.utc)).days
    gemeten = [r["rel"] for r in rijen if r["rel"] is not None]
    gem_rel = sum(gemeten) / len(gemeten) if gemeten else 0.0
    geraakt = [r for r in rijen if r["afstand"] is not None and r["afstand"] >= 0]

    # ── tegels ────────────────────────────────────────────────────────────────
    tegels = [
        ("Vermogen", "$%s" % format(round(nav.get("totaal_usd", 0)), ",d").replace(",", "."),
         "compleet gemeten" if nav.get("compleet") else "ONVOLLEDIG — ondergrens", "neutraal"),
        ("Netto per jaar", "−$103",
         "$57 rente tegen $160 infrastructuur", "kritiek"),
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
    tr = ""
    for r in rijen:
        rend = '<span class="%s">%+.1f%%</span>' % (
            "op" if (r["rend"] or 0) >= 0 else "neer", r["rend"]) if r["rend"] is not None else "—"
        rel = '<span class="%s">%+.1f%%</span>' % (
            "op" if (r["rel"] or 0) >= 0 else "neer", r["rel"]) if r["rel"] is not None else "—"
        if r["afstand"] is None:
            wacht = '<span class="zacht">%s</span>' % _esc(r["wacht"][:64])
        elif r["afstand"] >= 0:
            wacht = '<span class="geraakt">$%.0f — GERAAKT</span>' % r["wp"]
        else:
            wacht = '<span class="zacht">$%.0f · nog %.0f%%</span>' % (r["wp"], abs(r["afstand"]))
        tr += (
            '<tr><td class="tk">%s<div class="volnaam">%s</div></td>'
            '<td><span class="pil v-%s">%s</span></td>'
            '<td class="num">%s%s</td><td class="num">%s</td><td class="num">%s</td>'
            '<td class="num">%s</td><td class="num">%s</td><td>%s</td></tr>'
            % (_esc(r["t"]), _esc(r["naam"][:30]), r["verdict"].lower(), r["verdict"],
               ("%.2f" % r["score"]) if r["score"] else "—",
               ' <span class="vraag">%d?</span>' % r["onbekend"] if r["onbekend"] else "",
               ("%.2f" % r["p0"]) if r["p0"] else "—",
               ("%.2f" % r["nu"]) if r["nu"] else "—", rend, rel, wacht))

    beslis_html = "".join(
        '<div class="beslis"><div class="beslis-vraag">%s</div>'
        '<p class="beslis-uitleg">%s</p></div>' % (_esc(v), _esc(u))
        for v, u in BESLISSINGEN)

    # ── thema's ───────────────────────────────────────────────────────────────
    # Boven de namen, want dat is de vololgorde van de hiërarchie: een thema
    # levert kandidaten, het is nooit zelf een koopbeslissing.
    _rang = {"IN DE TRECHTER": 0, "VOLGEN": 1, "AFVALLER": 2}
    themas_gesorteerd = sorted(themas, key=lambda k: (_rang.get(k.get("verdict"), 3),
                                                      -(k.get("scores", {}).get("hardheid_geld") or 0)))
    tk = []
    for k in themas_gesorteerd:
        sc = k.get("scores", {})
        hardste = (k.get("bronnen") or [{}])[0]
        klasse = {"IN DE TRECHTER": "goed", "VOLGEN": "neutraal"}.get(k.get("verdict"), "kritiek")
        balk = "".join(
            '<span class="dim"><b>%s</b><i>%s</i></span>' % (_esc(lab), sc.get(sl) or "?")
            for lab, sl in [("geld", "hardheid_geld"), ("tolhuisje", "aard_tolhuisje"),
                            ("fase", "fase_doorbraak"), ("drukte", "drukte"),
                            ("instrument", "instrumenteerbaarheid")])
        tk.append(
            '<div class="thema">'
            '<div class="thema-kop"><h3>%s</h3><span class="pil %s">%s</span></div>'
            '<p class="thema-geld"><b>%s</b> — %s <span class="bron">(%s, %s)</span></p>'
            '<p class="thema-tol">Tolhuisje: <b>%s</b> · %s</p>'
            '<div class="dims">%s</div>'
            '<p class="thema-actie">%s</p></div>'
            % (_esc(k.get("naam", "?")), klasse, _esc(k.get("verdict", "?")),
               _esc(hardste.get("bedrag", "?")), _esc(hardste.get("wat", "")),
               _esc(hardste.get("bron", "")), _esc(hardste.get("datum", "")),
               _esc(k.get("tolhuisje_schakel", "?")), _esc(k.get("tolhuisje_soort", "")),
               balk,
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
        ("BENCH", _esc(bench_t)),
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
.t-goed{color:var(--goed)} .t-kritiek{color:var(--kritiek)} .t-neutraal{color:var(--inkt)}
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
.leeg{color:var(--zacht);font-size:.9rem}
.scroll{overflow-x:auto}
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

<div class="sectie">
  <h2>Waar het geld staat</h2>
  <p class="sectie-intro">Vier potjes. Het totaal werd tot 12 augustus 5,7% te laag
  gerapporteerd doordat het crypto-potje nergens werd meegeteld: ccxt noemt Bitcoin op
  Hyperliquid bij een tickernaam die naar een heel andere munt wijst. Dat was een
  rapportagefout en niets meer — het kasbeheer verdeelt zijn percentages over het VRIJE
  kapitaal, en dat is de juiste noemer voor die taak.</p>
  <div class="paneel">{{POTJES}}</div>
</div>

<div class="sectie">
  <h2>Het plan</h2>
  <p class="sectie-intro">Zes stappen. Drie klaar, twee lopen, één zit vast.</p>
  <div class="stappen">{{STAPPEN}}</div>
  <div class="noot"><strong>De blokkade:</strong> al het vermogen zit in crypto, terwijl
  het plan 40% in een wereldindexfonds wil. Er is geen route van USDC naar euro's op een
  bankrekening. Sinds 18 augustus is de opzet <strong>twee potjes naast elkaar</strong>:
  crypto en USDC blijven staan waar ze staan, DeGiro wordt gevuld met verse euro's. Geen
  omwisseling, geen extra rekening, en geen onomkeerbaar netwerk-risico. Wachten op het
  paspoort.</div>
</div>

<div class="sectie">
  <h2>Thema's</h2>
  <p class="sectie-intro">Gerangschikt op <strong>hardheid van het geld</strong> — is er
  budget vastgelegd, of verwacht iemand iets? Marktramingen tellen niet mee. Een thema is
  nooit zelf een koopbeslissing: het levert kandidaten voor de namen hieronder, en het
  instrument is daarna nog een aparte vraag. De vijf cijfers zijn 1-5, waarbij
  <em>drukte</em> omgekeerd werkt: hoog betekent dat de menigte weg is.</p>
  <div class="themas">{{THEMAS}}</div>
</div>

<div class="sectie">
  <h2>De twintig namen</h2>
  <p class="sectie-intro">Elke naam is beoordeeld op zes dimensies, met poorten vooraf en
  een vooraf vastgelegde koopdrempel. Vandaag is er niets koopbaar — niet vanwege de
  kalender, maar omdat geen enkele wachtvoorwaarde geraakt is. Gemeten tegen {{BENCH}}:
  <strong>{{GEMREL}}</strong> over {{NAANTAL}} namen, en dat is na een handvol dagen ruis,
  geen uitkomst. Afrekenen over {{DAGEN}} dagen.</p>
  <div class="paneel scroll"><table>
    <thead><tr><th>Naam</th><th>Oordeel</th><th class="num">Score</th>
    <th class="num">Bij scoring</th><th class="num">Nu</th><th class="num">Rend.</th>
    <th class="num">vs index</th><th>Koopdrempel</th></tr></thead>
    <tbody>{{RIJEN}}</tbody></table></div>
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
