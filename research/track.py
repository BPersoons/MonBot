"""Scorekaart-tracker — het oordeelloze deel van de onderzoekscadans.

    python research/track.py meet       # meet elke ledger-regel tegen de wereld-ETF
    python research/track.py due        # welke kaarten zijn toe aan herscoring?
    python research/track.py dashboard  # research/dashboard.html (voeg --snel toe om
                                        #   de cijferdatums over te slaan)
    python research/track.py check      # CI-modus: zwijgt tenzij er actie nodig is
    python research/track.py fundamentals  # toetst de fundamentele wacht- en
                                        #   terugkeervoorwaarden aan de kwartaalcijfers

Dit script scoort niets en beslist niets. Het meet en het signaleert; het oordeel
blijft een handmatige `/scorecard <TICKER>`-aanroep. Zie docs/PLAN_2026-08.md §2:
de onderzoekscadans wordt pas vanaf ~EUR 100k geautomatiseerd — daaronder met de hand.

`meet` beantwoordt de vraag uit research/README.md waar de hele ledger voor bestaat:
gingen hoge scores écht aan goede uitkomsten vooraf?
"""

import io
import json
import os
import sys
from datetime import datetime, timezone

LEDGER = os.path.join(os.path.dirname(__file__), "ledger.json")
TRACKING = os.path.join(os.path.dirname(__file__), "tracking.json")

RESCORE_AFTER_DAYS = 90  # ~1 kwartaal: een kaart veroudert op de dag dat de 10-Q landt


# --------------------------------------------------------------------------- data

def load_ledger():
    with io.open(LEDGER, encoding="utf-8") as fh:
        return json.load(fh)


def live_entries(ledger):
    """Actuele regels: superseded herscoringen tellen niet mee."""
    return [e for e in ledger["entries"] if not e.get("superseded_by")]


def fetch_prices(tickers):
    """Slotkoersen via yfinance. Faalt per ticker, niet in zijn geheel."""
    try:
        import yfinance as yf
    except ImportError:
        sys.exit("yfinance ontbreekt:  pip install yfinance")

    out = {}
    for t in sorted(set(tickers)):
        try:
            hist = yf.Ticker(t).history(period="5d")
            if hist.empty:
                out[t] = None
                continue
            out[t] = float(hist["Close"].iloc[-1])
        except Exception as exc:  # netwerk, delisting, ticker-hernoeming
            print("  ! %s: %s" % (t, exc), file=sys.stderr)
            out[t] = None
    return out


def avg_score(entry):
    """Gemiddelde over de ingevulde dimensies. None-dimensies tellen niet mee."""
    vals = [v for v in entry["scores"].values() if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def days_since(date_str):
    d = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - d).days


# --------------------------------------------------------------------------- meet

def cmd_meet(ledger):
    entries = live_entries(ledger)
    bench_ticker = ledger["_benchmark"]["ticker"]

    print("Koersen ophalen (%d namen + benchmark %s)...\n" % (len(entries), bench_ticker))
    prices = fetch_prices([e["ticker"] for e in entries] + [bench_ticker])

    bench_now = prices.get(bench_ticker)
    if bench_now is None:
        sys.exit("Benchmark %s niet op te halen — meting afgebroken." % bench_ticker)

    rows, skipped = [], []
    for e in entries:
        now = prices.get(e["ticker"])
        p0, b0 = e.get("price_at_score"), e.get("benchmark_price_at_score")
        if now is None or not p0 or not b0:
            skipped.append(e["ticker"])
            continue

        ret = (now / p0 - 1) * 100
        bench_ret = (bench_now / b0 - 1) * 100
        rows.append({
            "ticker": e["ticker"],
            "verdict": e["verdict"],
            "avg_score": avg_score(e),
            "scored_at": e["scored_at"],
            "days_held": days_since(e["scored_at"]),
            "price_at_score": p0,
            "price_now": round(now, 2),
            "return_pct": round(ret, 2),
            "benchmark_return_pct": round(bench_ret, 2),
            "relative_pct": round(ret - bench_ret, 2),
            "wait_price_below": e.get("wait_price_below"),
            "wait_triggered": bool(e.get("wait_price_below") and now <= e["wait_price_below"]),
        })

    rows.sort(key=lambda r: r["relative_pct"], reverse=True)

    print("%-6s %-9s %5s %8s %8s %8s %8s   %s" % (
        "", "verdict", "score", "toen", "nu", "rend.", "vs ETF", ""))
    print("-" * 74)
    for r in rows:
        flag = "  <- WACHTVOORWAARDE GERAAKT" if r["wait_triggered"] else ""
        print("%-6s %-9s %5s %8.2f %8.2f %+7.1f%% %+7.1f%%%s" % (
            r["ticker"], r["verdict"], r["avg_score"], r["price_at_score"],
            r["price_now"], r["return_pct"], r["relative_pct"], flag))

    if skipped:
        print("\nOvergeslagen (geen koers of geen prijs op scoredatum): %s" % ", ".join(skipped))

    # --- de vraag waar de ledger voor bestaat -------------------------------
    print("\n%s" % ("=" * 74))
    print("Gingen hoge scores aan goede uitkomsten vooraf?")
    print("=" * 74)

    for verdict in ("KOOPBAAR", "VOLGEN", "AFVALLER"):
        grp = [r for r in rows if r["verdict"] == verdict]
        if grp:
            avg = sum(r["relative_pct"] for r in grp) / len(grp)
            print("  %-9s n=%-3d gemiddeld %+.1f%% vs de wereld-ETF" % (verdict, len(grp), avg))

    if rows:
        overall = sum(r["relative_pct"] for r in rows) / len(rows)
        print("  %-9s n=%-3d gemiddeld %+.1f%% vs de wereld-ETF" % ("TOTAAL", len(rows), overall))

    n = len(rows)
    print("\nPoort: 6 maanden, >=20 namen, versla de wereld-ETF.")
    print("Stand: %d van 20 namen. %s" % (
        n, "Nog %d te scoren." % (20 - n) if n < 20 else "Aantal gehaald."))
    if n < 20:
        print("Let op: bij n=%d is elk gemiddelde hierboven ruis, geen uitkomst." % n)

    triggered = [r["ticker"] for r in rows if r["wait_triggered"]]
    if triggered:
        print("\n*** Wachtvoorwaarde geraakt: %s — kaart opnieuw langslopen. ***"
              % ", ".join(triggered))

    n_hist = save_snapshot(bench_ticker, bench_now, rows)
    print("\nSnapshot opgeslagen in research/tracking.json (%d in historie)." % n_hist)


def save_snapshot(bench_ticker, bench_now, rows):
    """Schrijft de meting van vandaag weg; een tweede run dezelfde dag overschrijft."""
    snapshot = {
        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "benchmark": bench_ticker,
        "benchmark_price": round(bench_now, 2),
        "rows": rows,
    }
    history = {"snapshots": []}
    if os.path.exists(TRACKING):
        try:
            with io.open(TRACKING, encoding="utf-8") as fh:
                history = json.load(fh)
        except (ValueError, IOError):
            pass  # corrupt of leeg: begin opnieuw, meting is toch idempotent

    history.setdefault("snapshots", [])
    history["snapshots"] = [
        s for s in history["snapshots"] if s.get("measured_at") != snapshot["measured_at"]
    ]
    history["snapshots"].append(snapshot)
    history["snapshots"].sort(key=lambda s: s["measured_at"])

    with io.open(TRACKING, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2, ensure_ascii=False)
    return len(history["snapshots"])


# --------------------------------------------------------------------------- check (CI)

def cmd_check(ledger):
    """Machine-modus voor CI: meet, schrijf snapshot, meld alleen wat actie vraagt.

    Zwijgt als er niets gebeurd is. Dat is het hele punt: een dagelijkse melding
    die altijd komt, leest niemand meer na een week.
    """
    entries = live_entries(ledger)
    bench_ticker = ledger["_benchmark"]["ticker"]
    prices = fetch_prices([e["ticker"] for e in entries] + [bench_ticker])
    bench_now = prices.get(bench_ticker)
    if bench_now is None:
        print("Benchmark %s niet op te halen — meting overgeslagen." % bench_ticker)
        _emit(False, "")
        return

    rows, triggered, stale = [], [], []
    for e in entries:
        now = prices.get(e["ticker"])
        p0, b0 = e.get("price_at_score"), e.get("benchmark_price_at_score")
        if now is None or not p0 or not b0:
            continue
        ret = (now / p0 - 1) * 100
        bench_ret = (bench_now / b0 - 1) * 100
        wp = e.get("wait_price_below")
        row = {
            "ticker": e["ticker"], "verdict": e["verdict"], "avg_score": avg_score(e),
            "scored_at": e["scored_at"], "days_held": days_since(e["scored_at"]),
            "price_at_score": p0, "price_now": round(now, 2),
            "return_pct": round(ret, 2), "benchmark_return_pct": round(bench_ret, 2),
            "relative_pct": round(ret - bench_ret, 2),
            "wait_price_below": wp,
            "wait_triggered": bool(wp and now <= wp),
        }
        rows.append(row)
        if row["wait_triggered"]:
            triggered.append((e, now, wp))
        if row["days_held"] >= RESCORE_AFTER_DAYS:
            stale.append(e["ticker"])

    save_snapshot(bench_ticker, bench_now, rows)
    avg_rel = sum(r["relative_pct"] for r in rows) / len(rows) if rows else 0.0
    print("%d namen gemeten · gemiddeld %+.2f%% vs %s · %d trigger(s) geraakt"
          % (len(rows), avg_rel, bench_ticker, len(triggered)))

    if not triggered and not stale:
        _emit(False, "")
        return

    lines = ["<b>Scorekaart-ledger</b>"]
    for e, now, wp in triggered:
        partial = e.get("wait_price_is_partial")
        lines.append(
            "\n⚠️ <b>%s</b> raakte de wachtprijs: $%.2f (drempel $%.2f)"
            % (e["ticker"], now, wp))
        # De prijs-notitie hoort bij de trigger; wait_conditions[0] is dat lang niet
        # altijd (bij LDOS is de prijs de tweede van twee OF-voorwaarden).
        if e.get("wait_price_note"):
            lines.append("Geraakte voorwaarde: %s" % e["wait_price_note"])
        conds = e.get("wait_conditions") or []
        if len(conds) > 1:
            lines.append("Volledige wachtvoorwaarde: %s" % " / ".join(conds))
        if partial:
            lines.append("<i>Let op: de prijs is maar EEN HELFT van een EN-voorwaarde — "
                         "controleer de andere helft in de kaart voordat je koopt.</i>")
        lines.append("Kaart: %s" % e.get("card", ""))
    if stale:
        lines.append("\n\U0001f4c5 Kaart ouder dan %d dagen: %s"
                     % (RESCORE_AFTER_DAYS, ", ".join(stale)))
    msg = "\n".join(lines)
    print(msg)
    _emit(True, msg)


def _emit(triggered, message):
    """Geeft het resultaat door aan GitHub Actions (indien daar), anders niets."""
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with io.open(out, "a", encoding="utf-8") as fh:
        fh.write("triggered=%s\n" % ("true" if triggered else "false"))
        fh.write("message<<SCOREKAART_EOF\n%s\nSCOREKAART_EOF\n" % message)


# --------------------------------------------------------------------------- due

def next_earnings(ticker):
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date") or []
            if dates:
                d = dates[0]
                return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10]
    except Exception:
        pass
    return None


def cmd_due(ledger):
    entries = live_entries(ledger)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print("Herscoring-check op %s\n" % today)

    due, waiting = [], []
    for e in entries:
        age = days_since(e["scored_at"])
        earnings = next_earnings(e["ticker"])
        reasons = []

        if age >= RESCORE_AFTER_DAYS:
            reasons.append("kaart %d dagen oud" % age)
        if earnings and earnings <= today and earnings > e["scored_at"][:10]:
            reasons.append("cijfers op %s" % earnings)

        row = (e["ticker"], e["verdict"], age, earnings or "?", reasons)
        (due if reasons else waiting).append(row)

    if due:
        print("TOE AAN HERSCORING  ->  /scorecard <TICKER> rescore")
        for t, v, age, earn, reasons in due:
            print("  %-6s %-9s %s" % (t, v, "; ".join(reasons)))
    else:
        print("Niets toe aan herscoring.")

    if waiting:
        print("\nNog niet toe:")
        for t, v, age, earn, _ in sorted(waiting, key=lambda r: r[2], reverse=True):
            print("  %-6s %-9s %3d dagen oud, volgende cijfers: %s" % (t, v, age, earn))

    print("\nEen kaart veroudert op de dag dat de 10-Q landt — cijfers zijn de klok,")
    print("niet de kalender. De %d-dagenregel is alleen een vangnet." % RESCORE_AFTER_DAYS)


# --------------------------------------------------------------- fundamentals

def cmd_fundamentals(ledger):
    """Toetst de fundamentele wacht- en terugkeervoorwaarden aan de kwartaalcijfers.

    Dit is de helft die er eerst niet was: de dagelijkse check keek alleen naar
    koersen, terwijl 12 van de 20 namen op iets fundamenteels wachten.
    """
    import fundamentals as fu

    entries = live_entries(ledger)
    te_toetsen = [e for e in entries
                  if e.get("wait_fundamental") or e.get("return_fundamental")]
    print("Kwartaalcijfers toetsen voor %d namen...\n" % len(te_toetsen))

    vervuld, onbekend, alleen_handmatig = [], [], []
    historie = fu.laad_historie()
    hist_voor = sum(len(v) for v in historie.values())

    for e in entries:
        if not (e.get("wait_fundamental") or e.get("return_fundamental")):
            alleen_handmatig.append(e["ticker"])
            continue

        is_return = bool(e.get("return_fundamental"))
        blok = e.get("return_fundamental") or e.get("wait_fundamental")
        metrieken, historie = fu.kwartaalmetrieken(e["ticker"], historie)
        ok, regels = fu.toets_voorwaarde(e["ticker"], blok, metrieken)

        stempel = {True: "VERVULD ", False: "nee     ", None: "onbekend",
                   "gedeeltelijk": "DEELS   "}[ok]
        soort = "terugkeer" if is_return else "wacht"
        print("%-6s %-9s %s %s" % (e["ticker"], stempel, soort,
                                   "(%s)" % blok.get("mode", "all")))
        for r_ok, uitleg in regels:
            merk = {True: "  +", False: "  -", None: "  ?"}[r_ok]
            print("%s %s" % (merk, uitleg))
        if e.get("manual_only_conditions"):
            print("   ! handmatig deel: %s" % e["manual_only_conditions"])

        if ok is True or ok == "gedeeltelijk":
            vervuld.append((e, is_return, ok == "gedeeltelijk"))
        elif ok is None:
            onbekend.append(e["ticker"])
        print()

    # Historie bewaren: yfinance geeft ~5 kwartalen, dus jaar-op-jaar over 2
    # kwartalen valt vaak buiten het venster. Onze eigen reeks groeit wel door.
    fu.bewaar_historie(historie)
    hist_na = sum(len(v) for v in historie.values())
    print("Metriek-historie: %d kwartaalregels over %d namen (+%d deze run)"
          % (hist_na, len(historie), hist_na - hist_voor))

    print("=" * 74)
    print("Vervuld: %d · onbekend: %d · niet vervuld: %d"
          % (len(vervuld), len(onbekend), len(te_toetsen) - len(vervuld) - len(onbekend)))
    if alleen_handmatig:
        print("Geen machine-toets (alleen prijs of handmatig): %s"
              % ", ".join(alleen_handmatig))
    if onbekend:
        print("Onbekend = niet meetbaar, NIET hetzelfde als gehaald: %s"
              % ", ".join(onbekend))

    if not vervuld:
        _emit(False, "")
        return

    regels_uit = ["<b>Scorekaart — fundamentele voorwaarde geraakt</b>"]
    for e, is_return, deels in vervuld:
        soort_txt = "terugkeervoorwaarde" if is_return else "wachtvoorwaarde"
        if deels:
            regels_uit.append(
                "\n⚠️ <b>%s</b> — het MEETBARE deel van de %s is gehaald, "
                "maar niet de hele voorwaarde. Dit is geen koopsignaal; controleer "
                "eerst het handmatige deel." % (e["ticker"], soort_txt))
        elif is_return:
            regels_uit.append("\n\U0001f504 <b>%s</b> (AFVALLER) voldoet aan zijn "
                              "terugkeervoorwaarde — herscoren." % e["ticker"])
        else:
            regels_uit.append("\n✅ <b>%s</b> voldoet aan zijn fundamentele "
                              "wachtvoorwaarde." % e["ticker"])
        conds = e.get("wait_conditions") or e.get("return_to_volgen_conditions") or []
        if conds:
            regels_uit.append("Voorwaarde: %s" % " / ".join(conds))
        if e.get("manual_only_conditions"):
            regels_uit.append("<i>Nog handmatig te controleren: %s</i>"
                              % e["manual_only_conditions"])
        regels_uit.append("Kaart: %s" % e.get("card", ""))
    msg = "\n".join(regels_uit)
    print("\n" + msg)
    _emit(True, msg)


# --------------------------------------------------------------------------- dashboard

DASHBOARD = os.path.join(os.path.dirname(__file__), "dashboard.html")
GATE_DATE = "2027-02-10"  # 6 maanden na de eerste ledger-regel (2026-08-10)


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def cmd_dashboard(ledger, with_earnings=True):
    entries = live_entries(ledger)
    bench_ticker = ledger["_benchmark"]["ticker"]
    prices = fetch_prices([e["ticker"] for e in entries] + [bench_ticker])
    bench_now = prices.get(bench_ticker)
    if bench_now is None:
        sys.exit("Benchmark %s niet op te halen." % bench_ticker)

    b0_ref = entries[0].get("benchmark_price_at_score")
    rows = []
    for e in entries:
        now = prices.get(e["ticker"])
        p0, b0 = e.get("price_at_score"), e.get("benchmark_price_at_score")
        if now is None or not p0 or not b0:
            continue
        ret = (now / p0 - 1) * 100
        bench_ret = (bench_now / b0 - 1) * 100
        wp = e.get("wait_price_below")
        rows.append({
            "ticker": e["ticker"], "name": e.get("name", ""),
            "verdict": e["verdict"], "avg": avg_score(e),
            "unknowns": sum(1 for v in e["scores"].values() if v is None),
            "p0": p0, "now": now, "ret": ret, "rel": ret - bench_ret,
            "wait_price": wp,
            "wait_gap": ((wp / now - 1) * 100) if wp else None,
            "wait_partial": e.get("wait_price_is_partial", False),
            "wait_text": (e.get("wait_conditions") or [e.get("wait_price_note") or ""])[0],
            "deciding": e.get("deciding_number", ""),
            "card": e.get("card", ""),
            "earnings": next_earnings(e["ticker"]) if with_earnings else None,
        })

    rows.sort(key=lambda r: r["rel"], reverse=True)
    bench_ret_all = (bench_now / b0_ref - 1) * 100 if b0_ref else 0.0
    avg_rel = sum(r["rel"] for r in rows) / len(rows) if rows else 0.0
    triggered = [r for r in rows if r["wait_price"] and r["now"] <= r["wait_price"]]
    days_left = (datetime.strptime(GATE_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                 - datetime.now(timezone.utc)).days
    maxabs = max([abs(r["rel"]) for r in rows] + [0.0])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- stat tiles ---------------------------------------------------------
    tiles = [
        ("Namen gescoord", "%d / 20" % len(rows), "poort-eis gehaald", "good"),
        ("Selectie vs wereld-ETF", "%+.1f%%" % avg_rel,
         "gemiddeld over %d namen · ruis onder 6 mnd" % len(rows),
         "good" if avg_rel > 0 else ("critical" if avg_rel < -1 else "neutral")),
        ("Wachtvoorwaarden geraakt", "%d" % len(triggered),
         (", ".join(r["ticker"] for r in triggered) if triggered
          else "geen — vandaag koop je niets"),
         "warning" if triggered else "neutral"),
        ("Dagen tot de poort", "%d" % max(days_left, 0),
         "meetmoment %s · geen koopverbod" % GATE_DATE, "neutral"),
    ]
    tiles_html = "".join(
        '<div class="tile"><div class="tile-label">%s</div>'
        '<div class="tile-value tone-%s">%s</div>'
        '<div class="tile-sub">%s</div></div>' % (_esc(l), t, _esc(v), _esc(s))
        for l, v, s, t in tiles)

    # --- diverging bars: relatief vs benchmark ------------------------------
    if maxabs < 0.05:
        chart_html = ('<p class="empty">Nog geen beweging: alle namen zijn gescoord op de '
                      'slotkoers die ook de laatste slotkoers is. Deze grafiek vult zich '
                      'vanaf de eerstvolgende handelsdag.</p>')
    else:
        bars = []
        for r in rows:
            frac = abs(r["rel"]) / maxabs * 50.0
            pos = r["rel"] >= 0
            side = ("left:50%%;width:%.2f%%" % frac) if pos else \
                   ("right:50%%;width:%.2f%%" % frac)
            bars.append(
                '<div class="barrow" data-tip="%s: %+.2f%% vs wereld-ETF">'
                '<div class="barlabel">%s</div>'
                '<div class="bartrack"><div class="zero"></div>'
                '<div class="bar %s" style="%s"></div></div>'
                '<div class="barval">%+.1f%%</div></div>'
                % (_esc(r["ticker"]), r["rel"], _esc(r["ticker"]),
                   "pos" if pos else "neg", side, r["rel"]))
        chart_html = ('<div class="chart">%s</div>'
                      '<div class="legend"><span class="sw pos"></span>boven de wereld-ETF'
                      '<span class="sw neg"></span>eronder</div>' % "".join(bars))

    # --- tabel --------------------------------------------------------------
    trs = []
    for r in rows:
        tone = {"KOOPBAAR": "good", "VOLGEN": "neutral", "AFVALLER": "critical"}[r["verdict"]]
        icon = {"KOOPBAAR": "●", "VOLGEN": "◐", "AFVALLER": "○"}[r["verdict"]]
        if r["wait_gap"] is None:
            wait = '<span class="muted">%s</span>' % _esc((r["wait_text"] or "—")[:58])
        else:
            hit = r["wait_gap"] >= 0
            wait = ('<span class="%s">$%.0f · %s%.1f%%%s</span>'
                    % ("hit" if hit else "muted", r["wait_price"],
                       "" if hit else "nog ", abs(r["wait_gap"]),
                       " (deel-voorwaarde)" if r["wait_partial"] else ""))
        trs.append(
            '<tr><td class="tk">%s</td>'
            '<td><span class="badge %s">%s %s</span></td>'
            '<td class="num">%.2f%s</td><td class="num">%.2f</td><td class="num">%.2f</td>'
            '<td class="num %s">%+.1f%%</td><td class="num %s">%+.1f%%</td><td>%s</td></tr>'
            % (_esc(r["ticker"]), tone, icon, r["verdict"],
               r["avg"], (' <span class="q">%d?</span>' % r["unknowns"]) if r["unknowns"] else "",
               r["p0"], r["now"],
               "up" if r["ret"] >= 0 else "down", r["ret"],
               "up" if r["rel"] >= 0 else "down", r["rel"], wait))

    # --- herscoring-agenda --------------------------------------------------
    if with_earnings:
        agenda = sorted([r for r in rows if r["earnings"]], key=lambda r: r["earnings"])
        items = "".join(
            '<li><b>%s</b> <span class="muted">%s</span> — %s</li>'
            % (_esc(r["ticker"]),
               "nu toe" if r["earnings"] <= today else r["earnings"],
               _esc(r["name"]))
            for r in agenda[:8])
        agenda_html = ("<ol class='agenda'>%s</ol>" % items) if items else \
            "<p class='empty'>Geen cijferdatums opgehaald.</p>"
    else:
        agenda_html = "<p class='empty'>Overgeslagen (--snel).</p>"

    html = _TEMPLATE
    for k, v in [("TODAY", today), ("TILES", tiles_html), ("CHART", chart_html),
                 ("ROWS", "".join(trs)), ("AGENDA", agenda_html),
                 ("BENCH", "%s $%.2f (%+.1f%% sinds scoredatum)"
                  % (bench_ticker, bench_now, bench_ret_all))]:
        html = html.replace("{{%s}}" % k, v)

    with io.open(DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("Dashboard geschreven: %s" % DASHBOARD)
    print("  %d namen · %d wachtvoorwaarde(n) geraakt · %d dagen tot de poort"
          % (len(rows), len(triggered), max(days_left, 0)))
    if triggered:
        print("  *** GERAAKT: %s ***" % ", ".join(r["ticker"] for r in triggered))


_TEMPLATE = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scorekaart-ledger</title>
<style>
:root{
  --surface:#fcfcfb; --plane:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,0.10);
  --pos:#2a78d6; --neg:#e34948; --neutralmid:#f0efec;
  --good:#0ca30c; --warning:#fab219; --critical:#d03b3b; --up:#006300;
}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){
  --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,0.10);
  --pos:#3987e5; --neg:#e66767; --neutralmid:#383835; --up:#0ca30c;
}}
:root[data-theme="dark"]{
  --surface:#1a1a19; --plane:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,0.10);
  --pos:#3987e5; --neg:#e66767; --neutralmid:#383835; --up:#0ca30c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;padding:28px 20px 60px}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:15px;margin:34px 0 12px;color:var(--ink2);font-weight:600}
.sub{color:var(--muted);font-size:13px;margin:0 0 24px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:14px 16px}
.tile-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.tile-value{font-size:28px;font-weight:600;margin:4px 0 2px;letter-spacing:-.02em}
.tile-sub{font-size:12px;color:var(--ink2)}
.tone-good{color:var(--good)} .tone-critical{color:var(--critical)}
.tone-warning{color:var(--warning)} .tone-neutral{color:var(--ink)}
.panel{background:var(--surface);border:1px solid var(--ring);border-radius:10px;padding:16px}
.chart{display:flex;flex-direction:column;gap:6px}
.barrow{display:grid;grid-template-columns:58px 1fr 62px;align-items:center;gap:10px;position:relative}
.barlabel{font-size:12px;color:var(--ink2);font-variant-numeric:tabular-nums}
.bartrack{position:relative;height:16px;background:var(--neutralmid);border-radius:3px}
.zero{position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--axis)}
.bar{position:absolute;top:2px;bottom:2px;border-radius:0 4px 4px 0;
  box-shadow:0 0 0 2px var(--surface)}
.bar.neg{border-radius:4px 0 0 4px}
.bar.pos{background:var(--pos)} .bar.neg{background:var(--neg)}
.barval{font-size:12px;text-align:right;font-variant-numeric:tabular-nums;color:var(--ink2)}
.barrow:hover::after{content:attr(data-tip);position:absolute;left:70px;top:-30px;z-index:5;
  background:var(--ink);color:var(--surface);font-size:12px;padding:5px 9px;border-radius:6px;
  white-space:nowrap;pointer-events:none}
.legend{margin-top:14px;font-size:12px;color:var(--ink2);display:flex;align-items:center;gap:6px}
.sw{width:11px;height:11px;border-radius:3px;display:inline-block;margin-left:14px}
.sw:first-child{margin-left:0}
.sw.pos{background:var(--pos)} .sw.neg{background:var(--neg)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.04em;
  color:var(--muted);font-weight:600;padding:0 10px 8px;border-bottom:1px solid var(--grid)}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
td{padding:9px 10px;border-bottom:1px solid var(--grid)}
tr:last-child td{border-bottom:none}
.tk{font-weight:600}
.badge{font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid var(--ring);
  white-space:nowrap}
.badge.good{color:var(--good)} .badge.critical{color:var(--critical)}
.badge.neutral{color:var(--ink2)}
.up{color:var(--up)} .down{color:var(--neg)}
.muted{color:var(--muted)} .q{color:var(--warning);font-size:11px}
.hit{color:var(--warning);font-weight:600}
.agenda{margin:0;padding-left:20px;font-size:13px;color:var(--ink2)}
.agenda li{margin:5px 0}
.empty{color:var(--muted);font-size:13px;margin:0}
.note{background:var(--surface);border:1px solid var(--ring);border-left:3px solid var(--warning);
  border-radius:8px;padding:12px 16px;font-size:13px;color:var(--ink2);margin-top:18px}
.scroll{overflow-x:auto}
</style></head><body><div class="wrap">
<h1>Scorekaart-ledger</h1>
<p class="sub">Bijgewerkt {{TODAY}} · benchmark {{BENCH}} · <code>python research/track.py dashboard</code></p>
<div class="tiles">{{TILES}}</div>

<h2>Rendement ten opzichte van de wereld-ETF</h2>
<div class="panel">{{CHART}}</div>

<h2>Alle namen</h2>
<div class="panel scroll"><table>
<thead><tr><th>Naam</th><th>Verdict</th><th class="num">Score</th>
<th class="num">Bij scoring</th><th class="num">Nu</th><th class="num">Rend.</th>
<th class="num">vs ETF</th><th>Wachtvoorwaarde</th></tr></thead>
<tbody>{{ROWS}}</tbody></table></div>

<h2>Eerstvolgende herscoringen</h2>
<div class="panel">{{AGENDA}}</div>

<div class="note"><b>Drie klokken, en ze lopen niet gelijk.</b>
<b>Dagelijks:</b> checken of een vooraf vastgelegde prijs-trigger geraakt is — dat is
uitvoering van een besluit dat al genomen is, geen reactie. <b>Op de kwartaalcijfers:</b>
herscoren, oftewel van mening mogen veranderen. <b>Maandelijks:</b> meten tegen de
wereld-ETF.<br><br>
Wat er níét mag: op de dag zelf een nieuwe reden verzinnen om te kopen omdat de koers hard
zakte. Namen met een <i>fundamentele</i> wachtvoorwaarde (twee kwartalen groei) worden
niet koopbaar door een koersdaling alleen — dan koopt de daling juist het risico in.
De poortdatum is een meetmoment, geen koopverbod.</div>
</div></body></html>"""


# --------------------------------------------------------------------------- main

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    ledger = load_ledger()
    if cmd == "meet":
        cmd_meet(ledger)
    elif cmd == "due":
        cmd_due(ledger)
    elif cmd == "dashboard":
        cmd_dashboard(ledger, with_earnings="--snel" not in sys.argv)
    elif cmd == "check":
        cmd_check(ledger)
    elif cmd == "fundamentals":
        cmd_fundamentals(ledger)
    else:
        sys.exit(__doc__)
