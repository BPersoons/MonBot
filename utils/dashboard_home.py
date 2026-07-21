"""
Compact unified home dashboard — served at / (EXP-009).

Vervangt het oude multi-tab swarm-dashboard als landingspagina. Bundelt in één
compacte kaart-grid de dingen die Bart daadwerkelijk bekijkt:

  1. Health-badge        — "Alle systemen gezond" (uit swarm_health)
  2. Trades              — open posities + laatste closes (de basis)
  3. Performance         — win-rate / profit factor + equity-curve (realized)
  4. Treasury            — HL/yield-allocatie samenvatting
  5. Thematic exposure   — budget + top-thema's (highlights)
  6. Roadmap             — actieve experimenten + laatste changelog + backlog

Elke kaart toont highlights met een doorklik naar de bestaande detailpagina
(/legacy, /treasury, /performance, /thematic-exposure). Alle data-reads zijn
defensief (utf-8, try/except) — ontbrekende state-files degraderen netjes.
"""

import json
import os
import html as _html
from datetime import datetime, timezone


# ────────────────────────── data helpers ──────────────────────────

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _safe_float(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def _is_closed(t):
    return str(t.get("status", "")).upper() == "CLOSED"


def _trade_pnl(t):
    """pnl_net is de echte winst; val terug op gross pnl voor oude records."""
    v = t.get("pnl_net")
    if v is None:
        v = t.get("pnl")
    return _safe_float(v)


def _epoch(t, field):
    """entry_time = raw epoch float; exit_time = ISO string. Normaliseer naar float."""
    v = t.get(field)
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _fmt_usd(v):
    v = _safe_float(v)
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"


def _pnl_color(v):
    v = _safe_float(v)
    return "var(--green)" if v > 0 else "var(--red)" if v < 0 else "var(--muted)"


def _sign(v):
    return "+" if _safe_float(v) >= 0 else ""


def _rel_time(epoch):
    if not epoch:
        return "—"
    try:
        delta = datetime.now(timezone.utc).timestamp() - epoch
        if delta < 3600:
            return f"{int(delta // 60)}m geleden"
        if delta < 86400:
            return f"{int(delta // 3600)}u geleden"
        return f"{int(delta // 86400)}d geleden"
    except Exception:
        return "—"


def _sparkline(values, color="var(--green)", w=260, h=48):
    """Inline SVG polyline uit een lijst floats (equity-curve)."""
    pts = [p for p in values if p is not None]
    if len(pts) < 2:
        return '<div style="color:var(--muted);font-size:.72rem">Onvoldoende data voor curve.</div>'
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1.0
    n = len(pts)
    coords = []
    for i, v in enumerate(pts):
        x = i / (n - 1) * w
        y = h - (v - lo) / rng * (h - 6) - 3
        coords.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(coords)
    last_col = "var(--green)" if pts[-1] >= pts[0] else "var(--red)"
    return (
        f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" preserveAspectRatio="none" '
        f'style="display:block">'
        f'<polyline points="{poly}" fill="none" stroke="{last_col}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


# ────────────────────────── section builders ──────────────────────────

def _build_health(agents):
    agents = agents or []
    OK = {"ACTIVE", "IDLE", "STARTING"}
    problems = []
    for a in agents:
        status = str(a.get("status", "")).upper()
        if status and status not in OK:
            name = a.get("agent_name") or a.get("name") or a.get("agent") or "onbekend"
            err = a.get("last_error") or ""
            problems.append((name, status, err))

    if not agents:
        return (
            '<div class="health warn"><span class="dot"></span>'
            'Geen health-data (dashboard draait, swarm_health niet bereikbaar)</div>'
        )
    if not problems:
        return (
            f'<div class="health ok"><span class="dot"></span>'
            f'Alle systemen gezond &middot; {len(agents)} agents actief</div>'
        )
    rows = "".join(
        f'<div class="prob"><b>{_html.escape(str(n))}</b> '
        f'<span class="badge">{_html.escape(s)}</span> '
        f'<span style="color:var(--muted)">{_html.escape(str(e)[:80] or "—")}</span></div>'
        for n, s, e in problems
    )
    return (
        f'<div class="health bad"><span class="dot"></span>'
        f'{len(problems)} agent(s) hebben aandacht nodig</div>{rows}'
    )


def _build_trades(trades):
    open_pos = [t for t in trades if str(t.get("status", "")).upper() == "OPEN"]
    closed = [t for t in trades if _is_closed(t)]
    closed.sort(key=lambda t: _epoch(t, "exit_time"), reverse=True)

    # open rows
    if open_pos:
        open_rows = ""
        for t in sorted(open_pos, key=lambda t: _epoch(t, "entry_time"), reverse=True):
            side = str(t.get("action", "")).upper()
            side_lbl = "LONG" if side == "BUY" else "SHORT" if side == "SELL" else side
            side_col = "var(--green)" if side == "BUY" else "var(--red)"
            upnl = _trade_pnl(t)
            open_rows += (
                f'<tr><td><b>{_html.escape(str(t.get("ticker", "?")))}</b></td>'
                f'<td style="color:{side_col}">{side_lbl}</td>'
                f'<td class="num" style="color:{_pnl_color(upnl)}">{_sign(upnl)}{_fmt_usd(upnl)}</td>'
                f'<td class="num" style="color:var(--muted)">stage {t.get("sl_stage", 0)}</td>'
                f'<td style="color:var(--muted)">{_rel_time(_epoch(t, "entry_time"))}</td></tr>'
            )
        open_html = f'<table><tr><th>Open</th><th>Zijde</th><th class="num">P&amp;L</th><th class="num">SL</th><th>Sinds</th></tr>{open_rows}</table>'
    else:
        open_html = '<div style="color:var(--muted);font-size:.8rem;padding:6px 0">Geen open posities.</div>'

    # recent closed rows (5)
    if closed:
        rows = ""
        for t in closed[:5]:
            pnl = _trade_pnl(t)
            side = str(t.get("action", "")).upper()
            side_lbl = "LONG" if side == "BUY" else "SHORT" if side == "SELL" else side
            rows += (
                f'<tr><td><b>{_html.escape(str(t.get("ticker", "?")))}</b></td>'
                f'<td style="color:var(--muted)">{side_lbl}</td>'
                f'<td class="num" style="color:{_pnl_color(pnl)}">{_sign(pnl)}{_fmt_usd(pnl)}</td>'
                f'<td class="num" style="color:var(--muted)">st{t.get("sl_stage", 0)}</td>'
                f'<td style="color:var(--muted)">{_rel_time(_epoch(t, "exit_time"))}</td></tr>'
            )
        closed_html = f'<table><tr><th>Recent gesloten</th><th></th><th class="num">P&amp;L</th><th></th><th></th></tr>{rows}</table>'
    else:
        closed_html = '<div style="color:var(--muted);font-size:.8rem;padding:6px 0">Nog geen gesloten trades.</div>'

    unreal = sum(_trade_pnl(t) for t in open_pos)
    kpi = (
        f'<div class="kpis">'
        f'<div><div class="k-lbl">Open posities</div><div class="k-val">{len(open_pos)}</div></div>'
        f'<div><div class="k-lbl">Onger. P&amp;L</div><div class="k-val" style="color:{_pnl_color(unreal)}">{_sign(unreal)}{_fmt_usd(unreal)}</div></div>'
        f'<div><div class="k-lbl">Gesloten totaal</div><div class="k-val">{len(closed)}</div></div>'
        f'</div>'
    )
    return _card("💹 Trades", kpi + open_html + closed_html, link=("/legacy", "Alle trades"), wide=True)


def _build_performance(trades, pnl_snapshots):
    closed = [t for t in trades if _is_closed(t)]
    now = datetime.now(timezone.utc).timestamp()

    def stats(window_days):
        cutoff = now - window_days * 86400
        sel = [t for t in closed if _epoch(t, "exit_time") >= cutoff] if window_days else closed
        wins = [t for t in sel if _trade_pnl(t) > 0]
        losses = [t for t in sel if _trade_pnl(t) < 0]
        n = len(wins) + len(losses)
        wr = len(wins) / n * 100 if n else 0.0
        gross_win = sum(_trade_pnl(t) for t in wins)
        gross_loss = abs(sum(_trade_pnl(t) for t in losses))
        pf = gross_win / gross_loss if gross_loss else (float("inf") if gross_win else 0.0)
        net = sum(_trade_pnl(t) for t in sel)
        return n, wr, pf, net

    n7, wr7, pf7, net7 = stats(7)
    n30, wr30, pf30, net30 = stats(30)

    def pf_str(pf):
        return "∞" if pf == float("inf") else f"{pf:.2f}"

    kpi = (
        f'<div class="kpis">'
        f'<div><div class="k-lbl">Win-rate 30d</div><div class="k-val">{wr30:.0f}%</div><div class="k-sub">{n30} trades</div></div>'
        f'<div><div class="k-lbl">Profit factor 30d</div><div class="k-val">{pf_str(pf30)}</div></div>'
        f'<div><div class="k-lbl">Net P&amp;L 30d</div><div class="k-val" style="color:{_pnl_color(net30)}">{_sign(net30)}{_fmt_usd(net30)}</div></div>'
        f'</div>'
    )
    sub = (
        f'<div style="font-size:.72rem;color:var(--muted);margin:2px 0 10px">'
        f'7d: WR {wr7:.0f}% &middot; PF {pf_str(pf7)} &middot; '
        f'<span style="color:{_pnl_color(net7)}">{_sign(net7)}{_fmt_usd(net7)}</span> ({n7} trades)</div>'
    )

    # equity curve = cumulatieve realized pnl over gesloten trades (chronologisch)
    chron = sorted(closed, key=lambda t: _epoch(t, "exit_time"))
    cum, running = [], 0.0
    for t in chron:
        running += _trade_pnl(t)
        cum.append(running)
    curve = (
        '<div style="font-size:.72rem;color:var(--muted);margin-bottom:4px;margin-top:4px">'
        'Cumulatieve realized P&amp;L</div>' + _sparkline(cum)
    )
    return _card("📈 Performance", kpi + sub + curve, link=("/performance", "Detail"))


def _build_treasury():
    state = _load_json("treasury_state.json", {})
    if not state:
        return _card("🏦 Treasury", '<div style="color:var(--muted);font-size:.8rem">Nog geen treasury-snapshot.</div>',
                     link=("/treasury", "Detail"))
    hl = state.get("hl_snapshot", {}) or {}
    hl_balance = _safe_float(hl.get("balance") or hl.get("total") or state.get("hl_balance"))
    yield_balances = state.get("yield_balances") or {}
    total_yield = _safe_float(state.get("total_yield") or sum(_safe_float(v) for v in yield_balances.values()))
    wallet = _safe_float(state.get("treasury_wallet_usdc"))
    total = _safe_float(state.get("total_portfolio")) or (hl_balance + total_yield + wallet)
    hl_pct = hl_balance / total * 100 if total else 0
    yld_pct = total_yield / total * 100 if total else 0

    kpi = (
        f'<div class="kpis">'
        f'<div><div class="k-lbl">Totaal</div><div class="k-val">{_fmt_usd(total)}</div></div>'
        f'<div><div class="k-lbl">HL trading</div><div class="k-val">{hl_pct:.0f}%</div><div class="k-sub">{_fmt_usd(hl_balance)}</div></div>'
        f'<div><div class="k-lbl">Yield</div><div class="k-val" style="color:var(--green)">{yld_pct:.0f}%</div><div class="k-sub">{_fmt_usd(total_yield)}</div></div>'
        f'</div>'
    )
    bar = (
        f'<div class="alloc-bar">'
        f'<div style="width:{hl_pct:.0f}%;background:var(--blue)"></div>'
        f'<div style="width:{yld_pct:.0f}%;background:var(--green)"></div></div>'
        f'<div style="font-size:.7rem;color:var(--muted);margin-top:4px">'
        f'<span style="color:var(--blue)">■</span> HL &nbsp; '
        f'<span style="color:var(--green)">■</span> Yield</div>'
    )
    # top protocollen
    active = sorted(((k, _safe_float(v)) for k, v in yield_balances.items() if _safe_float(v) > 1.0),
                    key=lambda x: x[1], reverse=True)[:3]
    prot = ""
    if active:
        prot = '<table style="margin-top:8px">' + "".join(
            f'<tr><td>{_html.escape(str(k))}</td><td class="num">{_fmt_usd(v)}</td></tr>'
            for k, v in active
        ) + "</table>"
    return _card("🏦 Treasury", kpi + bar + prot, link=("/treasury", "Detail"))


def _build_thematic():
    positions = _load_json("thematic_exposure_positions.json", {})
    report = _load_json("thematic_exposure_report.json", {})
    if not positions and not report:
        return _card("🎯 Thematic exposure",
                     '<div style="color:var(--muted);font-size:.8rem">Sleeve nog niet actief.</div>',
                     link=("/thematic-exposure", "Detail"))
    open_pos = {t: p for t, p in (positions.get("positions") or {}).items() if p.get("status") == "OPEN"}
    budget = _safe_float(positions.get("budget_usd"))
    cash = _safe_float(positions.get("cash_usd"))
    realized = _safe_float(positions.get("realized_pnl_usd"))
    total_val = sum(_safe_float(p.get("current_value") or p.get("value")) for p in open_pos.values())

    kpi = (
        f'<div class="kpis">'
        f'<div><div class="k-lbl">Budget</div><div class="k-val">{_fmt_usd(budget)}</div></div>'
        f'<div><div class="k-lbl">Open posities</div><div class="k-val">{len(open_pos)}</div></div>'
        f'<div><div class="k-lbl">Realized</div><div class="k-val" style="color:{_pnl_color(realized)}">{_sign(realized)}{_fmt_usd(realized)}</div></div>'
        f'</div>'
    )
    breadth = report.get("breadth_by_theme") or {}
    top = sorted(breadth.items(), key=lambda x: _safe_float(x[1]), reverse=True)[:4]
    themes_html = ""
    if top:
        themes_html = '<div class="chips">' + "".join(
            f'<span class="chip">{_html.escape(str(k))} '
            f'<b style="color:var(--cyan)">{_safe_float(v) * 100:.0f}%</b></span>'
            for k, v in top
        ) + "</div>"
    else:
        themes_html = '<div style="color:var(--muted);font-size:.75rem;margin-top:6px">Nog geen actieve thema-breedte.</div>'
    return _card("🎯 Thematic exposure", kpi + themes_html, link=("/thematic-exposure", "Detail"))


def _build_roadmap():
    rm = _load_json("roadmap.json", {})
    if not rm:
        return _card("🗺️ Roadmap", '<div style="color:var(--muted);font-size:.8rem">Geen roadmap-data.</div>')

    # actieve experimenten
    exps = [e for e in rm.get("experiments", []) if str(e.get("status", "")).upper() in ("ACTIVE", "PAUSED")]
    exp_html = ""
    if exps:
        for e in exps[:3]:
            st = str(e.get("status", "")).upper()
            col = "var(--green)" if st == "ACTIVE" else "var(--yellow)"
            exp_html += (
                f'<div class="rm-row"><span class="badge" style="background:{col};color:#000">{st}</span> '
                f'<b>{_html.escape(str(e.get("id", "")))}</b> '
                f'{_html.escape(str(e.get("name", ""))[:60])}</div>'
            )
    else:
        exp_html = '<div style="color:var(--muted);font-size:.75rem">Geen lopende experimenten.</div>'

    # laatste changelog
    changelog = rm.get("changelog", [])
    cl = changelog[0] if changelog else {}
    cl_html = ""
    if cl:
        cl_html = (
            f'<div class="rm-sub">Laatste update &middot; {_html.escape(str(cl.get("date", "")))}</div>'
            f'<div style="font-size:.78rem"><b>{_html.escape(str(cl.get("version", ""))[:70])}</b></div>'
            f'<div style="font-size:.74rem;color:var(--muted);margin-top:2px">'
            f'{_html.escape(str(cl.get("summary", ""))[:180])}…</div>'
        )

    # top backlog (HIGH prio)
    backlog = [b for b in rm.get("backlog", []) if str(b.get("priority", "")).upper() == "HIGH"]
    bl_html = ""
    if backlog:
        bl_html = '<div class="rm-sub">Backlog (high)</div>' + "".join(
            f'<div class="rm-row" style="font-size:.76rem">• {_html.escape(str(b.get("title", ""))[:60])}</div>'
            for b in backlog[:3]
        )

    body = (
        '<div class="rm-sub">Lopende experimenten</div>' + exp_html +
        '<div style="height:8px"></div>' + cl_html +
        '<div style="height:8px"></div>' + bl_html
    )
    return _card("🗺️ Roadmap", body, wide=True)


# ────────────────────────── layout ──────────────────────────

def _card(title, body, link=None, wide=False):
    link_html = ""
    if link:
        href, label = link
        link_html = f'<a class="card-link" href="{href}">{_html.escape(label)} →</a>'
    cls = "card wide" if wide else "card"
    return (
        f'<div class="{cls}">'
        f'<div class="card-head"><span class="card-title">{title}</span>{link_html}</div>'
        f'{body}</div>'
    )


def build_home_html(agents=None):
    trades = _load_json("trade_log.json", [])
    if not isinstance(trades, list):
        trades = []
    pnl_snapshots = _load_json("pnl_snapshots.json", [])
    dash = _load_json("dashboard.json", {})
    cycle = dash.get("cycle_count", "—")
    updated = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    health = _build_health(agents)
    cards = (
        _build_trades(trades) +
        _build_performance(trades, pnl_snapshots) +
        _build_treasury() +
        _build_thematic() +
        _build_roadmap()
    )

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Agent Trader — Overzicht</title>
<style>
:root{{--bg:#0a0e17;--card:rgba(17,24,39,0.8);--border:rgba(75,85,99,0.4);--text:#f9fafb;--muted:#9ca3af;--green:#10b981;--red:#ef4444;--yellow:#f59e0b;--blue:#3b82f6;--purple:#8b5cf6;--cyan:#06b6d4}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:20px;
background-image:radial-gradient(ellipse at 20% 0%,rgba(59,130,246,0.12) 0%,transparent 50%),radial-gradient(ellipse at 80% 100%,rgba(139,92,246,0.08) 0%,transparent 50%)}}
.wrap{{max-width:1280px;margin:0 auto}}
header{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:18px}}
h1{{font-size:1.3rem;font-weight:700;letter-spacing:-.5px}}
.meta{{font-size:.78rem;color:var(--muted)}}
nav a{{color:var(--muted);text-decoration:none;font-size:.78rem;margin-left:14px;transition:color .15s}}
nav a:hover{{color:var(--text)}}
.health{{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:12px;font-weight:600;font-size:.9rem;margin-bottom:8px;border:1px solid var(--border)}}
.health .dot{{width:10px;height:10px;border-radius:50%}}
.health.ok{{background:rgba(16,185,129,0.1)}}.health.ok .dot{{background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite}}
.health.warn{{background:rgba(245,158,11,0.1)}}.health.warn .dot{{background:var(--yellow)}}
.health.bad{{background:rgba(239,68,68,0.12)}}.health.bad .dot{{background:var(--red)}}
.prob{{font-size:.78rem;padding:4px 16px}}
.badge{{display:inline-block;padding:1px 7px;border-radius:6px;font-size:.66rem;font-weight:700;background:var(--border)}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:8px}}
.card{{background:var(--card);backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:14px;padding:18px}}
.card.wide{{grid-column:1 / -1}}
.card-head{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}}
.card-title{{font-size:1rem;font-weight:700}}
.card-link{{font-size:.74rem;color:var(--cyan);text-decoration:none}}
.card-link:hover{{text-decoration:underline}}
.kpis{{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:10px}}
.k-lbl{{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}}
.k-val{{font-size:1.35rem;font-weight:700;line-height:1.3}}
.k-sub{{font-size:.68rem;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;margin-top:6px}}
th{{text-align:left;padding:5px 8px;font-size:.66rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}}
td{{padding:5px 8px;font-size:.82rem;border-bottom:1px solid rgba(75,85,99,0.15)}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
.alloc-bar{{display:flex;height:12px;border-radius:6px;overflow:hidden;margin-top:8px;background:var(--border)}}
.chips{{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}}
.chip{{background:var(--border);border-radius:8px;padding:5px 10px;font-size:.76rem}}
.rm-row{{font-size:.8rem;padding:3px 0}}
.rm-sub{{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin:2px 0 4px}}
footer{{text-align:center;color:var(--muted);font-size:.72rem;margin-top:24px;padding-top:16px;border-top:1px solid var(--border)}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
@media(max-width:820px){{.grid{{grid-template-columns:1fr}}.card.wide{{grid-column:auto}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>⚡ Agent Trader</h1>
    <div class="meta">Cycle {cycle} &middot; bijgewerkt {updated} &middot; ververst elke 60s</div>
  </div>
  <nav>
    <a href="/legacy">Swarm-detail</a>
    <a href="/performance">Performance</a>
    <a href="/treasury">Treasury</a>
    <a href="/thematic-exposure">Thematic</a>
    <a href="/v2">v2</a>
  </nav>
</header>
{health}
<div class="grid">
{cards}
</div>
<footer>Agent Trader autonomous swarm &middot; single-page overzicht</footer>
</div>
</body>
</html>"""
