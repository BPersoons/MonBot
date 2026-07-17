"""
Thematic Dip Sleeve dashboard — served at /thematic-dip (EXP-008).

Shows:
- Portfolio overview (budget, cash, value, realized/unrealized P&L)
- Per-theme rollup (a ticker can belong to multiple themes — its value/P&L
  is shown under each, so theme totals can overlap by design)
- Open positions per ticker (theme(s), tranche stage, entry, current value)
- DCA history per ticker (every individual tranche buy, from trade_log.json)
- Tickers pending Telegram classification review
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime, timezone


_CSS = """
:root{--bg:#0a0e17;--card:rgba(17,24,39,0.8);--border:rgba(75,85,99,0.4);--text:#f9fafb;--muted:#9ca3af;--green:#10b981;--red:#ef4444;--yellow:#f59e0b;--blue:#3b82f6;--purple:#8b5cf6;--cyan:#06b6d4}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;background-image:radial-gradient(ellipse at 20% 0%,rgba(59,130,246,0.15) 0%,transparent 50%),radial-gradient(ellipse at 80% 100%,rgba(139,92,246,0.1) 0%,transparent 50%)}
.container{max-width:1400px;margin:0 auto;padding:24px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:12px}
.header-right{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.logo{display:flex;align-items:center;gap:12px}
.logo-icon{width:44px;height:44px;background:linear-gradient(135deg,var(--purple),var(--cyan));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
h1{font-size:1.5rem;font-weight:700;background:linear-gradient(135deg,#fff,#9ca3af);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.live{display:flex;align-items:center;gap:8px;font-size:.875rem;color:var(--muted)}
.pulse-dot{width:10px;height:10px;background:var(--green);border-radius:50%;animation:pulse 2s infinite;flex-shrink:0}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.7;transform:scale(1.1)}}
.nav-back{font-size:.8rem;color:var(--blue);text-decoration:none;padding:6px 12px;border:1px solid rgba(59,130,246,0.3);border-radius:6px;white-space:nowrap}
.section{margin-bottom:32px}
.section-header{display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap}
.section-title{font-size:.9rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;white-space:nowrap}
.section-line{flex:1;height:1px;background:var(--border);min-width:20px}
.card{background:var(--card);backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:14px;padding:20px;position:relative}
footer{text-align:center;padding:24px;color:var(--muted);font-size:.8rem;border-top:1px solid var(--border);margin-top:32px}
code{font-family:monospace;font-size:.85em;color:var(--cyan)}
.portfolio-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:4px}
.theme-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:8px 12px;font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}
td{padding:8px 12px;font-size:.82rem;border-bottom:1px solid rgba(75,85,99,0.15)}
.badge{display:inline-block;border-radius:8px;font-size:.7rem;padding:2px 8px;font-weight:600;margin:1px}
@media(max-width:900px){
  .portfolio-grid{grid-template-columns:repeat(2,1fr)}
  .theme-grid{grid-template-columns:1fr}
  .container{padding:16px}
  h1{font-size:1.25rem}
}
@media(max-width:500px){
  .portfolio-grid{grid-template-columns:1fr}
  .card{padding:14px}
  .section{margin-bottom:20px}
}
"""


def _load_json(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _fmt_usd(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return "—"


def _fmt_pct(v) -> str:
    try:
        return f"{float(v):+.1f}%"
    except Exception:
        return "—"


def _pnl_color(v) -> str:
    try:
        v = float(v)
    except Exception:
        return "var(--muted)"
    if v > 0:
        return "var(--green)"
    if v < 0:
        return "var(--red)"
    return "var(--muted)"


def _fmt_time(iso_or_epoch) -> str:
    try:
        if isinstance(iso_or_epoch, (int, float)):
            dt = datetime.fromtimestamp(iso_or_epoch, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(iso_or_epoch).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


# ── Section builders ────────────────────────────────────────────────────────

def _build_portfolio_overview(positions: dict) -> str:
    open_pos = {t: p for t, p in positions.get("positions", {}).items() if p.get("status") == "OPEN"}
    total_value = sum(float(p.get("current_value_usd", 0) or 0) for p in open_pos.values())
    total_cost = sum(float(p.get("cost_basis_usd", 0) or 0) for p in open_pos.values())
    unrealized = total_value - total_cost
    cash = float(positions.get("cash_usd", 0) or 0)
    budget = float(positions.get("budget_usd", 0) or 0)
    realized = float(positions.get("realized_pnl_usd", 0) or 0)

    cards = [
        ("Budget", _fmt_usd(budget), "var(--text)"),
        ("Vrij (cash)", _fmt_usd(cash), "var(--cyan)"),
        ("Posities open", str(len(open_pos)), "var(--text)"),
        ("Waarde open posities", _fmt_usd(total_value), "var(--text)"),
        ("Ongerealiseerd P&L", _fmt_usd(unrealized), _pnl_color(unrealized)),
        ("Gerealiseerd P&L", _fmt_usd(realized), _pnl_color(realized)),
    ]
    return '<div class="portfolio-grid">' + "".join(
        f'<div class="card"><div style="font-size:.72rem;color:var(--muted);text-transform:uppercase;'
        f'letter-spacing:.5px;margin-bottom:6px">{label}</div>'
        f'<div style="font-size:1.3rem;font-weight:700;color:{color}">{value}</div></div>'
        for label, value, color in cards
    ) + "</div>"


def _build_theme_rollup(positions: dict, report: dict) -> str:
    open_pos = {t: p for t, p in positions.get("positions", {}).items() if p.get("status") == "OPEN"}
    breadth = report.get("breadth_by_theme") or {}
    if not breadth and not open_pos:
        return '<div class="card" style="color:var(--muted)">Nog geen data.</div>'

    by_theme: dict[str, list] = {}
    for ticker, pos in open_pos.items():
        for theme_id in (pos.get("themes") or {}):
            by_theme.setdefault(theme_id, []).append((ticker, pos))
    all_themes = sorted(set(breadth.keys()) | set(by_theme.keys()))
    if not all_themes:
        return '<div class="card" style="color:var(--muted)">Nog geen thema-data.</div>'

    cards = []
    for theme_id in all_themes:
        members = by_theme.get(theme_id, [])
        value = sum(float(p.get("current_value_usd", 0) or 0) for _, p in members)
        cost = sum(float(p.get("cost_basis_usd", 0) or 0) for _, p in members)
        pnl = value - cost
        b = breadth.get(theme_id, 0.0)
        active = " · <span style=\"color:var(--yellow)\">actief</span>" if b >= 0.30 else ""
        tickers_str = ", ".join(_html.escape(t) for t, _ in members) or "geen open posities"
        cards.append(
            f'<div class="card"><div style="font-weight:700;margin-bottom:4px">{_html.escape(theme_id)}{active}</div>'
            f'<div style="font-size:.75rem;color:var(--muted);margin-bottom:8px">breedte: {b*100:.0f}%</div>'
            f'<div style="font-size:1.1rem;font-weight:700">{_fmt_usd(value)}</div>'
            f'<div style="font-size:.8rem;color:{_pnl_color(pnl)}">{_fmt_usd(pnl)} ongerealiseerd</div>'
            f'<div style="font-size:.72rem;color:var(--muted);margin-top:6px">{tickers_str}</div></div>'
        )
    return '<div class="theme-grid">' + "".join(cards) + "</div>"


def _build_positions_table(positions: dict) -> str:
    open_pos = {t: p for t, p in positions.get("positions", {}).items() if p.get("status") == "OPEN"}
    if not open_pos:
        return '<div class="card" style="color:var(--muted)">Geen open posities.</div>'
    rows = []
    for ticker, pos in sorted(open_pos.items(), key=lambda kv: -float(kv[1].get("current_value_usd", 0) or 0)):
        value = float(pos.get("current_value_usd", 0) or 0)
        cost = float(pos.get("cost_basis_usd", 0) or 0)
        pnl = value - cost
        pnl_pct = (pnl / cost * 100) if cost else 0.0
        themes_str = ", ".join(_html.escape(t) for t in (pos.get("themes") or {})) or "—"
        rows.append(
            "<tr>"
            f"<td style='font-weight:600'>{_html.escape(ticker)}</td>"
            f"<td>{themes_str}</td>"
            f"<td>T{pos.get('tranche_stage', 1)}</td>"
            f"<td>{float(pos.get('quantity', 0) or 0):.4f}</td>"
            f"<td>{_fmt_usd(pos.get('avg_entry_price'))}</td>"
            f"<td>{_fmt_usd(value)}</td>"
            f"<td style='color:{_pnl_color(pnl)}'>{_fmt_usd(pnl)} ({_fmt_pct(pnl_pct)})</td>"
            f"<td>{_fmt_time(pos.get('opened_at'))}</td>"
            "</tr>"
        )
    return (
        '<div class="card table-scroll"><table><thead><tr>'
        "<th>Ticker</th><th>Thema's</th><th>Tranche</th><th>Qty</th><th>Gem. entry</th>"
        "<th>Waarde</th><th>P&amp;L</th><th>Geopend</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _build_dca_history(trade_log: list) -> str:
    dip_trades = [t for t in trade_log if t.get("thematic_dip")]
    if not dip_trades:
        return '<div class="card" style="color:var(--muted)">Nog geen DCA-tranches uitgevoerd.</div>'
    by_ticker: dict[str, list] = {}
    for t in dip_trades:
        by_ticker.setdefault(t.get("ticker", "?"), []).append(t)

    blocks = []
    for ticker, trades in sorted(by_ticker.items()):
        trades = sorted(trades, key=lambda t: t.get("entry_time", 0))
        rows = "".join(
            "<tr>"
            f"<td>{_fmt_time(t.get('entry_time'))}</td>"
            f"<td>{_html.escape(str(t.get('action', 'BUY')))}</td>"
            f"<td>{float(t.get('quantity', 0) or 0):.4f}</td>"
            f"<td>{_fmt_usd(t.get('entry_price'))}</td>"
            f"<td>{_fmt_usd(t.get('size_usd'))}</td>"
            f"<td>{_html.escape(str(t.get('status', '?')))}</td>"
            "</tr>"
            for t in trades
        )
        blocks.append(
            f'<div class="card" style="margin-bottom:12px"><div style="font-weight:700;margin-bottom:8px">{_html.escape(ticker)}</div>'
            '<div class="table-scroll"><table><thead><tr>'
            "<th>Tijd</th><th>Actie</th><th>Qty</th><th>Prijs</th><th>Bedrag</th><th>Status</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div></div>"
        )
    return "".join(blocks)


def _build_pending_classifications(themes_cfg: dict) -> str:
    pending = [
        (t, e) for t, e in themes_cfg.get("tickers", {}).items()
        if e.get("status") in ("PENDING_REVIEW", "PENDING_MANUAL")
    ]
    if not pending:
        return '<div class="card" style="color:var(--muted)">Geen tickers wachten op review.</div>'
    rows = []
    for ticker, entry in sorted(pending):
        safe_ticker = _html.escape(ticker)
        themes_str = ", ".join(f"{k} ({v:.2f})" for k, v in (entry.get("themes") or {}).items()) or "geen voorstel"
        status_color = "var(--yellow)" if entry.get("status") == "PENDING_REVIEW" else "var(--red)"
        approve_btn = (
            f'<button onclick="dipAction(\'approve\',\'{safe_ticker}\')" '
            'style="background:var(--green);color:#000;border:none;border-radius:6px;padding:4px 10px;'
            'font-size:.72rem;font-weight:600;cursor:pointer;margin:2px">✓ Approve</button>'
            if entry.get("themes") else ""
        )
        rows.append(
            "<tr>"
            f"<td style='font-weight:600'>{safe_ticker}</td>"
            f"<td style='color:{status_color}'>{_html.escape(entry.get('status', ''))}</td>"
            f"<td>{_html.escape(themes_str)}</td>"
            "<td>"
            f"{approve_btn}"
            f'<button onclick="dipAction(\'ignore\',\'{safe_ticker}\')" '
            'style="background:var(--red);color:#fff;border:none;border-radius:6px;padding:4px 10px;'
            'font-size:.72rem;font-weight:600;cursor:pointer;margin:2px">✗ Ignore</button><br>'
            f'<input type="text" id="edit-{safe_ticker}" placeholder="thema:gewicht,thema:gewicht" '
            'style="width:200px;font-size:.72rem;padding:3px 6px;border-radius:5px;border:1px solid var(--border);'
            'background:rgba(0,0,0,0.3);color:var(--text);margin:2px">'
            f'<button onclick="dipEdit(\'{safe_ticker}\')" '
            'style="background:var(--blue);color:#fff;border:none;border-radius:6px;padding:4px 10px;'
            'font-size:.72rem;font-weight:600;cursor:pointer;margin:2px">Edit+Approve</button>'
            "</td>"
            "</tr>"
        )
    return (
        '<div class="card table-scroll"><table><thead><tr>'
        "<th>Ticker</th><th>Status</th><th>Voorstel</th><th>Actie</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        '<div style="font-size:.75rem;color:var(--muted);margin-top:10px">'
        "Ook mogelijk via Telegram: <code>/dipapprove</code>, <code>/dipedit</code>, <code>/dipignore</code> "
        "(zie <code>/help</code>).</div></div>"
    )


# ── Page assembly ────────────────────────────────────────────────────────────

def build_thematic_dip_html() -> str:
    positions = _load_json("thematic_dip_positions.json", {"positions": {}, "cash_usd": 0, "budget_usd": 0})
    report = _load_json("thematic_dip_report.json", {})
    themes_cfg = _load_json("config/thematic_dip_themes.json", {"themes": {}, "tickers": {}})
    trade_log = _load_json("trade_log.json", [])

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report_ts = (report.get("generated_at") or "")[:16].replace("T", " ") + " UTC" if report.get("generated_at") else "—"
    pending_count = sum(
        1 for e in themes_cfg.get("tickers", {}).values()
        if e.get("status") in ("PENDING_REVIEW", "PENDING_MANUAL")
    )
    pending_badge = (
        f'<span style="background:var(--yellow);color:#000;border-radius:10px;font-size:.7rem;padding:2px 8px;font-weight:700;margin-left:8px">{pending_count} te reviewen</span>'
        if pending_count else ""
    )
    active_themes = [t for t, b in (report.get("breadth_by_theme") or {}).items() if b >= 0.30]
    active_str = ", ".join(_html.escape(t) for t in active_themes) if active_themes else "geen"

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Thematic Dip Sleeve — Agent Trader</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
<script>
async function dipAction(action, ticker) {{
  try {{
    const res = await fetch('/api/thematic-dip/' + action, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ticker}})
    }});
    const data = await res.json();
    if (data.ok) {{ location.reload(); }}
    else {{ alert('Fout: ' + (data.error || data.message || 'onbekend')); }}
  }} catch(e) {{ alert('Netwerk fout: ' + e); }}
}}
async function dipEdit(ticker) {{
  const input = document.getElementById('edit-' + ticker);
  const theme_spec = input ? input.value.trim() : '';
  if (!theme_spec) {{ alert('Vul eerst thema:gewicht in (bv. semiconductors:0.6)'); return; }}
  try {{
    const res = await fetch('/api/thematic-dip/edit', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ticker, theme_spec}})
    }});
    const data = await res.json();
    if (data.ok) {{ location.reload(); }}
    else {{ alert('Fout: ' + (data.error || data.message || 'onbekend')); }}
  }} catch(e) {{ alert('Netwerk fout: ' + e); }}
}}
</script>
</head>
<body>
<div class="container">

<header>
  <div class="logo">
    <div class="logo-icon">🧠</div>
    <div>
      <h1>Thematic Dip Sleeve{pending_badge}</h1>
      <div style="font-size:.75rem;color:var(--muted)">EXP-008 — crash-scanner + DCA, actieve thema's: {active_str}</div>
    </div>
  </div>
  <div class="header-right">
    <div class="live"><div class="pulse-dot"></div>{now}</div>
    <a href="/" class="nav-back">← Dashboard</a>
    <a href="/treasury" class="nav-back">Treasury →</a>
  </div>
</header>

<div class="section">
  <div class="section-header">
    <span class="section-title">Portfolio overzicht</span>
    <div class="section-line"></div>
    <span style="font-size:.75rem;color:var(--muted)">Scoring: {report_ts}</span>
  </div>
  {_build_portfolio_overview(positions)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Per thema</span>
    <div class="section-line"></div>
    <span style="font-size:.75rem;color:var(--muted)">een ticker kan onder meerdere thema's vallen — totalen kunnen overlappen</span>
  </div>
  {_build_theme_rollup(positions, report)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Open posities</span>
    <div class="section-line"></div>
  </div>
  {_build_positions_table(positions)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">DCA-historie per ticker</span>
    <div class="section-line"></div>
  </div>
  {_build_dca_history(trade_log)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Wacht op classificatie-review{pending_badge}</span>
    <div class="section-line"></div>
  </div>
  {_build_pending_classifications(themes_cfg)}
</div>

<footer>
  Auto-refresh elke 5 min &nbsp;|&nbsp; Data: thematic_dip_positions.json · thematic_dip_report.json · config/thematic_dip_themes.json
  &nbsp;|&nbsp; <a href="/" style="color:var(--blue)">Dashboard</a>
  &nbsp;|&nbsp; <a href="/treasury" style="color:var(--blue)">Treasury</a>
</footer>

</div>
</body>
</html>"""
