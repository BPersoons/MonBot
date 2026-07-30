"""
Dashboard Server v2 — Swarm Command Center (redesigned)
Served at /v2 on port 8080, alongside the original v1 at /.

5 tabs: Overview | Decisions | Intelligence | Trades | RSI
"""
import json
import logging
import os
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta, date

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CSS + HTML shell
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """
:root{--bg:#0a0e17;--card:rgba(17,24,39,0.8);--border:rgba(75,85,99,0.4);--text:#f9fafb;--muted:#9ca3af;--green:#10b981;--red:#ef4444;--yellow:#f59e0b;--blue:#3b82f6;--purple:#8b5cf6;--cyan:#06b6d4}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;background-image:radial-gradient(ellipse at 20% 0%,rgba(59,130,246,0.15) 0%,transparent 50%),radial-gradient(ellipse at 80% 100%,rgba(139,92,246,0.1) 0%,transparent 50%)}
.container{max-width:1400px;margin:0 auto;padding:24px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;padding-bottom:24px;border-bottom:1px solid var(--border)}
.logo{display:flex;align-items:center;gap:12px}
.logo-icon{width:48px;height:48px;background:linear-gradient(135deg,var(--blue),var(--purple));border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:24px}
h1{font-size:1.75rem;font-weight:700;background:linear-gradient(135deg,#fff,#9ca3af);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.live{display:flex;align-items:center;gap:8px;font-size:.875rem;color:var(--muted)}
.pulse-dot{width:10px;height:10px;background:var(--green);border-radius:50%;animation:pulse 2s infinite;box-shadow:0 0 10px rgba(16,185,129,0.3)}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.7;transform:scale(1.1)}}

/* Tabs */
.tabs{display:flex;gap:10px;margin-bottom:24px;flex-wrap:wrap}
.tab-btn{background:rgba(255,255,255,0.05);border:1px solid var(--border);color:var(--muted);padding:10px 20px;border-radius:8px;cursor:pointer;font-weight:600;transition:all 0.2s}
.tab-btn:hover{background:rgba(255,255,255,0.1);color:var(--text)}
.tab-btn.active{background:var(--blue);color:white;border-color:var(--blue)}
.tab-content{display:none}
.tab-content.active{display:block}

/* Section */
.section{margin-bottom:32px}
.section-header{display:flex;align-items:center;gap:10px;margin-bottom:16px}
.section-title{font-size:1rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.section-line{flex:1;height:1px;background:var(--border)}
.section-badge{font-size:.7rem;padding:3px 8px;border-radius:8px;background:rgba(59,130,246,0.15);color:var(--blue)}

/* Card */
.card{background:var(--card);backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:16px;padding:24px}

/* Traffic light agent grid */
.agent-grid{display:flex;flex-wrap:wrap;gap:10px;padding:12px;background:var(--card);border:1px solid var(--border);border-radius:12px}
.agent-dot-wrap{position:relative;display:inline-flex;flex-direction:column;align-items:center;gap:4px;padding:8px 12px;border-radius:8px;cursor:pointer;transition:background .15s;min-width:90px}
.agent-dot-wrap:hover{background:rgba(255,255,255,0.06)}
.agent-dot{width:14px;height:14px;border-radius:50%;flex-shrink:0;transition:box-shadow .2s}
.agent-dot.ACTIVE,.agent-dot.WORKING{background:var(--green);box-shadow:0 0 8px rgba(16,185,129,0.6)}
.agent-dot.IDLE{background:var(--yellow);box-shadow:0 0 6px rgba(245,158,11,0.4)}
.agent-dot.ERROR{background:var(--red);box-shadow:0 0 8px rgba(239,68,68,0.6);animation:err-pulse 1s infinite}
.agent-dot.STARTING{background:var(--blue)}
@keyframes err-pulse{0%,100%{opacity:1}50%{opacity:.4}}
.agent-label{font-size:.68rem;color:var(--muted);white-space:nowrap}
.agent-cycle{font-size:.62rem;color:rgba(156,163,175,0.6)}

/* Agent tooltip */
.agent-tooltip{display:none;position:absolute;z-index:200;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);background:#1e293b;border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:240px;max-width:320px;box-shadow:0 8px 24px rgba(0,0,0,0.5);font-size:.75rem;line-height:1.5;color:var(--text);pointer-events:none}
.agent-dot-wrap:hover .agent-tooltip{display:block}
.tt-title{font-weight:700;margin-bottom:8px;color:var(--cyan);font-size:.82rem}
.tt-row{display:flex;justify-content:space-between;gap:12px;padding:2px 0}
.tt-label{color:var(--muted);white-space:nowrap}
.tt-val{color:var(--text);font-weight:500;text-align:right;word-break:break-word}

/* Health banner */
.health-strip{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:10px;margin-bottom:12px;font-size:.85rem;font-weight:600}
.health-strip.ok{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.25);color:var(--green)}
.health-strip.warn{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:var(--red)}
.health-strip.boot{background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.25);color:var(--yellow)}

/* Tables */
.data-table{width:100%;border-collapse:collapse;font-size:.83rem}
.data-table th{text-align:left;padding:7px 10px;font-size:.68rem;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);border-bottom:1px solid var(--border);white-space:nowrap}
.data-table td{padding:7px 10px;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:middle}
.data-table tr:hover{background:rgba(255,255,255,0.02)}

/* CPO backlog */
.cpo-category{margin-bottom:20px}
.cpo-cat-header{font-size:.75rem;font-weight:700;color:var(--cyan);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;padding:4px 0;border-bottom:1px solid rgba(6,182,212,0.2)}
.cpo-item{background:var(--card);border:1px solid var(--border);border-left:3px solid var(--border);border-radius:8px;padding:12px 16px;margin-bottom:6px;cursor:pointer;transition:border-color .2s}
.cpo-item:hover{border-left-color:var(--blue)}
.cpo-item.HIGH{border-left-color:var(--red)}
.cpo-item.MID{border-left-color:var(--yellow)}
.cpo-item.LOW{border-left-color:var(--blue)}
.cpo-item-header{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.cpo-item-title{font-size:.9rem;font-weight:600;color:var(--text)}
.cpo-item-meta{display:flex;gap:6px;align-items:center;flex-shrink:0}
.cpo-item-desc{font-size:.8rem;color:var(--muted);line-height:1.45;margin-top:6px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cpo-item.expanded .cpo-item-desc{display:block;-webkit-line-clamp:unset}
.pri-badge{padding:2px 8px;border-radius:10px;font-size:.65rem;font-weight:700;text-transform:uppercase}
.pri-badge.HIGH{background:rgba(239,68,68,0.2);color:var(--red)}
.pri-badge.MID{background:rgba(245,158,11,0.2);color:var(--yellow)}
.pri-badge.LOW{background:rgba(59,130,246,0.2);color:var(--blue)}

/* Missed trade setup */
.miss-card{background:var(--card);border:1px solid var(--border);border-left:4px solid var(--yellow);border-radius:10px;padding:14px 18px;margin-bottom:8px}

/* Mstat */
.mstat{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center}
.mstat .big{font-size:1.6rem;font-weight:700}
.mstat .lbl{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:4px}

/* Decision cards */
.decision-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:12px;border-left:4px solid var(--muted);transition:transform .2s}
.decision-card:hover{transform:translateX(3px)}
.decision-card.BUY,.decision-card.LONG{border-left-color:var(--green)}
.decision-card.SELL,.decision-card.SHORT{border-left-color:var(--red)}
.decision-card.NO_GO,.decision-card.SKIP{border-left-color:var(--muted)}
.decision-card.MONITOR{border-left-color:var(--yellow)}
.decision-card.BUILD_CASE{border-left-color:var(--cyan)}
.dec-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:6px}
.dec-ticker{font-size:1.1rem;font-weight:700}
.dec-verdict{padding:4px 12px;border-radius:20px;font-size:.78rem;font-weight:700;text-transform:uppercase}
.dec-verdict.BUY,.dec-verdict.LONG,.dec-verdict.BUILD_CASE{background:rgba(16,185,129,0.2);color:var(--green)}
.dec-verdict.SELL,.dec-verdict.SHORT{background:rgba(239,68,68,0.2);color:var(--red)}
.dec-verdict.NO_GO,.dec-verdict.SKIP{background:rgba(156,163,175,0.2);color:var(--muted)}
.dec-verdict.MONITOR{background:rgba(245,158,11,0.2);color:var(--yellow)}
.dec-reason{font-size:.85rem;line-height:1.45;color:var(--text);margin-bottom:8px}
.dec-next{font-size:.78rem;padding:6px 10px;background:rgba(6,182,212,0.08);border-left:3px solid var(--cyan);border-radius:0 6px 6px 0;color:var(--cyan)}

/* RSI */
.explainer-card{background:linear-gradient(135deg,rgba(59,130,246,0.1),rgba(139,92,246,0.1));border:1px solid var(--blue);border-radius:12px;padding:20px;margin-bottom:24px}
.explainer-title{font-size:1.1rem;font-weight:700;color:var(--blue);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.explainer-text{font-size:.9rem;line-height:1.6;color:var(--text)}

/* Pagination */
.pg-btn{padding:4px 14px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:.82rem}

/* Tip */
.tip{position:relative;cursor:help}
.tip .tip-text{visibility:hidden;opacity:0;position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:.7rem;font-weight:400;line-height:1.5;white-space:normal;width:260px;z-index:100;pointer-events:none;transition:opacity .15s;box-shadow:0 4px 16px rgba(0,0,0,0.4)}
.tip:hover .tip-text{visibility:visible;opacity:1}

footer{text-align:center;padding:24px;color:var(--muted);font-size:.875rem;border-top:1px solid var(--border);margin-top:32px}

@media (max-width:640px){
  .container{padding:12px}
  header{flex-direction:column;align-items:flex-start;gap:10px}
  h1{font-size:1.25rem}
  .tabs{gap:6px}
  .tab-btn{padding:8px 14px;font-size:.8rem}
  .agent-grid{gap:6px}
}
"""

_HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>Swarm v2 | Agent Trader</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>{css}</style>
<script>
document.addEventListener("DOMContentLoaded", () => {{
    const t = sessionStorage.getItem('v2Tab') || 'overview';
    showTab(t);
}});
function showTab(id) {{
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    const tc = document.getElementById('tab-' + id);
    const tb = document.getElementById('btn-' + id);
    if (tc) tc.classList.add('active');
    if (tb) tb.classList.add('active');
    sessionStorage.setItem('v2Tab', id);
}}
function toggleCpo(el) {{
    el.classList.toggle('expanded');
}}
</script>
</head>
<body>
<div class="container">
<header>
  <div class="logo">
    <div class="logo-icon">&#x1F3AF;</div>
    <div>
      <h1>Swarm Command Center <span style="font-size:.9rem;color:var(--muted)">v2</span></h1>
      <span style="color:var(--muted);font-size:.875rem">Agent Trader &mdash; Redesigned Dashboard</span>
    </div>
  </div>
  <div class="live">
    <div class="pulse-dot"></div>
    <span>Live &bull; {timestamp}</span>
  </div>
</header>

<div class="tabs">
  <div id="btn-overview" class="tab-btn active" onclick="showTab('overview')">&#x1F3E0; Overview</div>
  <div id="btn-decisions" class="tab-btn" onclick="showTab('decisions')">&#x1F4CB; Decisions</div>
  <div id="btn-intelligence" class="tab-btn" onclick="showTab('intelligence')">&#x1F9E0; Intelligence</div>
  <div id="btn-trades" class="tab-btn" onclick="showTab('trades')">&#x1F4B0; Trades</div>
  <div id="btn-rsi" class="tab-btn" onclick="showTab('rsi')">&#x1F9EC; RSI</div>
</div>

<div id="tab-overview" class="tab-content active">
{tab_overview}
</div>
<div id="tab-decisions" class="tab-content">
{tab_decisions}
</div>
<div id="tab-intelligence" class="tab-content">
{tab_intelligence}
</div>
<div id="tab-trades" class="tab-content">
{tab_trades}
</div>
<div id="tab-rsi" class="tab-content">
{tab_rsi}
</div>

<footer>&#x1F680; Powered by Agent Trader Swarm &bull; Supabase &bull; Hyperliquid &bull; Auto-refresh 30s</footer>
</div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _is_closed(t):
    s = str(t.get('status', '')).upper()
    return s.startswith('CLOSED') or s == 'EXPIRED'


def _ts(t):
    v = t.get('exit_time') or t.get('entry_time') or ''
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def _load_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Overview
# ─────────────────────────────────────────────────────────────────────────────

def _build_agent_grid(agents):
    """Compact traffic-light grid: one dot + label + cycle per agent."""
    if not agents:
        return '<div class="health-strip boot">&#x23F3; No agent health data — waiting for first heartbeat</div>'

    dots = []
    for a in sorted(agents, key=lambda x: x.get('agent_name', '')):
        name = a.get('agent_name', 'Unknown')
        status = str(a.get('status', 'IDLE')).upper()
        cycle = a.get('cycle_count', 0)
        meta = a.get('metadata') or {}
        if not isinstance(meta, dict):
            meta = {}

        task = str(meta.get('current_task', '') or a.get('current_task', '') or '—')[:80]
        last_pulse_raw = str(a.get('last_pulse', '') or '')
        last_error = str(meta.get('last_error', '') or '')[:120]

        # Format last pulse as time-ago
        pulse_str = '—'
        try:
            lp = datetime.fromisoformat(last_pulse_raw.replace('Z', '+00:00').replace('+00:00+00:00', '+00:00'))
            diff = datetime.now(lp.tzinfo) - lp
            secs = int(diff.total_seconds())
            if secs < 120:
                pulse_str = f'{secs}s ago'
            elif secs < 3600:
                pulse_str = f'{secs // 60}m ago'
            else:
                pulse_str = f'{secs // 3600}h ago'
        except Exception:
            pulse_str = last_pulse_raw[:16] or '—'

        error_row = ''
        if last_error and status == 'ERROR':
            error_row = f'<div class="tt-row"><span class="tt-label">Error</span><span class="tt-val" style="color:var(--red)">{last_error}</span></div>'

        tooltip = f'''<div class="agent-tooltip">
            <div class="tt-title">{name}</div>
            <div class="tt-row"><span class="tt-label">Status</span><span class="tt-val">{status}</span></div>
            <div class="tt-row"><span class="tt-label">Task</span><span class="tt-val">{task}</span></div>
            <div class="tt-row"><span class="tt-label">Last pulse</span><span class="tt-val">{pulse_str}</span></div>
            <div class="tt-row"><span class="tt-label">Cycles</span><span class="tt-val">{cycle}</span></div>
            {error_row}
        </div>'''

        dots.append(f'''<div class="agent-dot-wrap">
            <div class="agent-dot {status}"></div>
            <div class="agent-label">{name}</div>
            <div class="agent-cycle">#{cycle}</div>
            {tooltip}
        </div>''')

    # Health banner
    errors = [a for a in agents if str(a.get('status', '')).upper() == 'ERROR']
    if errors:
        banner = f'<div class="health-strip warn">&#x26A0;&#xFE0F; {len(errors)} agent(s) in ERROR state: {", ".join(a.get("agent_name","?") for a in errors)}</div>'
    else:
        banner = '<div class="health-strip ok">&#x2705; All agents running normally</div>'

    return f'''{banner}
<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F6A6; Agent Status</span>
    <span class="section-badge">{len(agents)} agents</span>
    <span class="section-line"></span>
  </div>
  <div class="agent-grid">{"".join(dots)}</div>
</div>'''


def _build_open_positions(trades, positions_status):
    """Open positions table for the Overview tab."""
    open_trades = sorted(
        [t for t in trades if t.get('status') in ('OPEN', 'PLACED')],
        key=_ts, reverse=True
    )

    if not open_trades:
        return '''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F7E2; Open Positions</span>
    <span class="section-badge">0</span>
    <span class="section-line"></span>
  </div>
  <p style="color:var(--muted);padding:10px 0">Geen open posities.</p>
</div>'''

    TH = '<th>'
    rows = []
    total_unreal = 0.0
    for t in open_trades:
        ticker   = t.get('ticker', '?')
        action   = (t.get('action') or 'BUY').upper()
        direction = 'LONG' if action == 'BUY' else 'SHORT'
        dir_color = 'var(--green)' if action == 'BUY' else 'var(--red)'
        entry    = _safe_float(t.get('entry_price') or t.get('intended_price'))
        qty      = _safe_float(t.get('quantity'))
        value    = _safe_float(t.get('trade_value')) or (entry * qty)
        tp       = _safe_float(t.get('take_profit'))
        sl       = _safe_float(t.get('stop_loss'))
        entry_ts = _safe_float(t.get('entry_time'))

        ps = positions_status.get(ticker, {})
        current_price  = ps.get('current_price')
        unrealized_pnl = ps.get('unrealized_pnl')
        pnl_pct        = ps.get('pnl_pct')

        elapsed = '—'
        if entry_ts:
            secs = int(_time.time() - entry_ts)
            elapsed = f"{secs // 3600}h {(secs % 3600) // 60}m" if secs >= 3600 else f"{secs // 60}m"

        price_html = f'${current_price:.4f}' if current_price else '<span style="color:var(--muted)">—</span>'
        tp_html    = f'<span style="color:var(--green)">${tp:.4f}</span>' if tp else '<span style="color:var(--muted)">—</span>'
        sl_html    = f'<span style="color:var(--red)">${sl:.4f}</span>' if sl else '<span style="color:var(--muted)">—</span>'

        if unrealized_pnl is not None:
            total_unreal += unrealized_pnl
            upnl_color = 'var(--green)' if unrealized_pnl >= 0 else 'var(--red)'
            sign = '+' if unrealized_pnl >= 0 else ''
            upnl_html = f'<span style="color:{upnl_color};font-weight:600">{sign}${unrealized_pnl:.2f} ({sign}{_safe_float(pnl_pct):.1f}%)</span>'
        else:
            upnl_html = '<span style="color:var(--muted)">—</span>'

        rows.append(f'''<tr>
            <td style="font-weight:600">{ticker}</td>
            <td><span style="color:{dir_color}">{direction}</span></td>
            <td>${entry:.4f}</td>
            <td>{price_html}</td>
            <td>{tp_html}</td>
            <td>{sl_html}</td>
            <td style="color:var(--muted)">${value:.2f}</td>
            <td>{upnl_html}</td>
            <td style="color:var(--muted)">{elapsed}</td>
        </tr>''')

    upnl_color = 'var(--green)' if total_unreal >= 0 else 'var(--red)'
    sign = '+' if total_unreal >= 0 else ''
    summary = f'''<div style="display:flex;gap:24px;padding:8px 0 14px;flex-wrap:wrap">
        <div><div style="color:var(--muted);font-size:.72rem">OPEN</div><div style="font-weight:700;font-size:1.1rem">{len(open_trades)}</div></div>
        <div><div style="color:var(--muted);font-size:.72rem">UNREALIZED P&amp;L</div><div style="font-weight:700;font-size:1.1rem;color:{upnl_color}">{sign}${total_unreal:.2f}</div></div>
    </div>'''

    return f'''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F7E2; Open Positions</span>
    <span class="section-badge">{len(open_trades)}</span>
    <span class="section-line"></span>
  </div>
  {summary}
  <div style="overflow-x:auto">
  <table class="data-table">
    <thead><tr>{TH}Ticker</th>{TH}Dir</th>{TH}Entry</th>{TH}Current</th>{TH}TP</th>{TH}SL</th>{TH}Value</th>{TH}Unreal P&amp;L</th>{TH}Open</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  </div>
</div>'''


def _build_missed_trades(hours=12):
    """BUILD_CASE decisions from decision_history.json that didn't execute in the last N hours."""
    try:
        history = _load_json('decision_history.json', [])
        if not isinstance(history, list):
            return ''
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        missed = []
        for d in history:
            if str(d.get('decision', '')).upper() not in ('BUILD_CASE', 'BUY', 'LONG', 'SELL', 'SHORT'):
                continue
            try:
                ts = datetime.fromisoformat(str(d.get('timestamp', '')).replace('Z', '+00:00').replace('+00:00+00:00', '+00:00'))
                if ts.replace(tzinfo=None) < cutoff:
                    continue
            except Exception:
                continue
            # Only show ones that were not ultimately executed
            final = str(d.get('final_decision', d.get('decision', ''))).upper()
            if final in ('EXECUTED', 'BUY', 'LONG', 'SELL', 'SHORT') and d.get('order_id'):
                continue
            missed.append(d)

        if not missed:
            return f'''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4CC; Missed Trade Setups <span style="font-size:.75rem;font-weight:400;color:var(--muted)">(last {hours}h BUILD_CASE)</span></span>
    <span class="section-line"></span>
  </div>
  <p style="color:var(--muted);padding:8px 0">Geen gemiste setups de afgelopen {hours}u.</p>
</div>'''

        cards = []
        for d in missed[:10]:
            ticker  = d.get('ticker', '?')
            score   = _safe_float(d.get('score'))
            reason  = str(d.get('reason', d.get('narrative', '—')))[:180]
            current = _safe_float(d.get('current_price'))
            target  = _safe_float(d.get('target_entry_price'))
            dist    = abs(current - target) / current * 100 if current and target else 0.0
            dist_html = f'<span style="color:{"var(--green)" if dist < 2 else "var(--yellow)"}">{dist:.1f}%</span>' if dist else '—'
            ts_str  = str(d.get('timestamp', ''))[:16].replace('T', ' ')
            cards.append(f'''<div class="miss-card">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
    <span style="font-weight:700;color:var(--cyan)">{ticker}</span>
    <div style="display:flex;gap:10px;font-size:.78rem">
      <span>Score: <strong style="color:var(--green)">{score:.2f}</strong></span>
      <span>Dist: {dist_html}</span>
      <span style="color:var(--muted)">{ts_str}</span>
    </div>
  </div>
  <div style="font-size:.8rem;color:var(--muted);margin-top:6px;line-height:1.4">{reason}</div>
</div>''')

        return f'''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4CC; Missed Trade Setups <span style="font-size:.75rem;font-weight:400;color:var(--muted)">(last {hours}h BUILD_CASE)</span></span>
    <span class="section-badge">{len(missed)}</span>
    <span class="section-line"></span>
  </div>
  {"".join(cards)}
</div>'''
    except Exception as e:
        logger.debug(f'_build_missed_trades error: {e}')
        return ''


def _build_mini_pnl(trades, pnl_snapshots):
    """Mini daily P&L bar chart (160px) + stats bar."""
    from collections import defaultdict
    daily_pnl = defaultdict(float)
    total_pnl = 0.0
    wins = losses = 0
    win_sum = 0.0
    closed_trades = []
    for t in trades:
        if not _is_closed(t):
            continue
        pnl = _safe_float(t.get('pnl'))
        exit_time = t.get('exit_time') or ''
        try:
            day = datetime.fromisoformat(str(exit_time).replace('Z', '+00:00')).strftime('%Y-%m-%d')
            daily_pnl[day] += pnl
        except Exception:
            pass
        total_pnl += pnl
        if pnl > 0:
            wins += 1
            win_sum += pnl
        elif pnl < 0:
            losses += 1
        closed_trades.append(t)

    today = date.today()
    days = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    vals = [round(daily_pnl.get(d, 0), 2) for d in days]
    short_days = [d[5:] for d in days]
    bar_colors = ['rgba(16,185,129,0.7)' if v >= 0 else 'rgba(239,68,68,0.7)' for v in vals]

    if not any(v != 0 for v in vals):
        return ''

    total_trades = wins + losses
    win_rate = wins / total_trades * 100 if total_trades else 0
    avg_win = win_sum / wins if wins else 0

    pnl_color = 'var(--green)' if total_pnl >= 0 else 'var(--red)'
    sign = '+' if total_pnl >= 0 else ''
    stats = f'''<div style="display:flex;gap:28px;flex-wrap:wrap;margin-bottom:14px">
      <div><div style="color:var(--muted);font-size:.72rem">TOTAL P&amp;L</div><div style="font-weight:700;color:{pnl_color}">{sign}${total_pnl:.2f}</div></div>
      <div><div style="color:var(--muted);font-size:.72rem">WIN RATE</div><div style="font-weight:700">{win_rate:.0f}%</div></div>
      <div><div style="color:var(--muted);font-size:.72rem">AVG WIN</div><div style="font-weight:700;color:var(--green)">${avg_win:.2f}</div></div>
      <div><div style="color:var(--muted);font-size:.72rem">CLOSED TRADES</div><div style="font-weight:700">{total_trades}</div></div>
    </div>'''

    chart_id = 'miniPnlOverview'
    return f'''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4C8; P&amp;L</span>
    <span class="section-line"></span>
  </div>
  {stats}
  <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px">
    <div style="position:relative;height:160px"><canvas id="{chart_id}"></canvas></div>
  </div>
</div>
<script>
new Chart(document.getElementById('{chart_id}'), {{
    type: 'bar',
    data: {{
        labels: {json.dumps(short_days)},
        datasets: [{{
            label: 'Daily P&L ($)',
            data: {json.dumps(vals)},
            backgroundColor: {json.dumps(bar_colors)},
            borderRadius: 3
        }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ ticks: {{ color: '#9ca3af', font: {{ size: 9 }}, maxRotation: 45 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
            y: {{ ticks: {{ color: '#9ca3af', font: {{ size: 9 }}, callback: v => '$' + v.toFixed(0) }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
        }}
    }}
}});
</script>'''


def build_tab_overview(agents, trades, positions_status, pnl_snapshots):
    return (
        _build_open_positions(trades, positions_status)
        + _build_agent_grid(agents)
        + _build_missed_trades()
        + _build_mini_pnl(trades, pnl_snapshots)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — Decisions (same as original ProjectLead tab)
# ─────────────────────────────────────────────────────────────────────────────

def build_tab_decisions():
    """Latest decisions from decision_history.json."""
    try:
        history = _load_json('decision_history.json', [])
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []

    if not history:
        return '<div style="color:var(--muted);padding:24px">Nog geen beslissingen opgeslagen.</div>'

    # Latest 30 decisions, newest first
    recent = sorted(history, key=lambda d: d.get('timestamp', ''), reverse=True)[:30]

    def _verdict_cls(dec):
        d = str(dec).upper()
        if d in ('BUY', 'LONG', 'BUILD_CASE'):
            return 'BUY'
        if d in ('SELL', 'SHORT'):
            return 'SELL'
        if d == 'MONITOR':
            return 'MONITOR'
        return 'NO_GO'

    cards = []
    for d in recent:
        ticker   = d.get('ticker', '?')
        dec      = str(d.get('decision', 'UNKNOWN')).upper()
        score    = _safe_float(d.get('score'))
        reason   = str(d.get('reason', d.get('narrative', '')))[:400]
        next_s   = str(d.get('next_step', d.get('final_decision', '')))
        ts       = str(d.get('timestamp', ''))[:16].replace('T', ' ')
        tf       = d.get('timeframe', '')
        direction = d.get('direction', '')
        vcls     = _verdict_cls(dec)

        score_color = 'var(--green)' if score >= 0.4 else ('var(--yellow)' if score >= 0.2 else 'var(--muted)')
        dir_html = f'<span style="color:{"var(--green)" if direction == "LONG" else "var(--red)"}"> {direction}</span>' if direction else ''
        next_html = f'<div class="dec-next" style="margin-top:8px">&#x2192; {next_s}</div>' if next_s else ''

        cards.append(f'''<div class="decision-card {vcls}">
  <div class="dec-header">
    <span class="dec-ticker">{ticker}{dir_html} <span style="font-size:.78rem;color:var(--muted);font-weight:400">{tf}</span></span>
    <div style="display:flex;gap:8px;align-items:center">
      <span style="font-size:.82rem;color:{score_color};font-weight:700">{score:.2f}</span>
      <span class="dec-verdict {vcls}">{dec}</span>
      <span style="color:var(--muted);font-size:.72rem">{ts}</span>
    </div>
  </div>
  <div class="dec-reason">{reason}</div>
  {next_html}
</div>''')

    return f'''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4CB; Recent Decisions</span>
    <span class="section-badge">{len(recent)} shown</span>
    <span class="section-line"></span>
  </div>
  {"".join(cards)}
</div>'''


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 — Intelligence (CPO backlog + LLM diagnostics + LLM cost)
# ─────────────────────────────────────────────────────────────────────────────

_CATEGORY_ORDER = ['FEATURE', 'PERFORMANCE', 'RELIABILITY', 'DATA', 'SECURITY', 'OTHER']
_PRIORITY_ORDER = {'HIGH': 0, 'MID': 1, 'LOW': 2}


def _build_backlog_section(backlog_items):
    """CPO backlog grouped by category, sorted HIGH→MID→LOW."""
    if not backlog_items:
        return '''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4CB; Improvement Backlog</span>
    <span class="section-line"></span>
  </div>
  <p style="color:var(--muted)">Geen backlog items — ProductOwner heeft nog niet geanalyseerd.</p>
</div>'''

    # Group by category
    groups = defaultdict(list)
    for item in backlog_items:
        cat = str(item.get('category', 'OTHER')).upper()
        if cat not in _CATEGORY_ORDER:
            cat = 'OTHER'
        groups[cat].append(item)

    # Sort within each group by priority
    for cat in groups:
        groups[cat].sort(key=lambda x: _PRIORITY_ORDER.get(str(x.get('priority', 'LOW')).upper(), 3))

    sections_html = []
    for cat in _CATEGORY_ORDER:
        items = groups.get(cat)
        if not items:
            continue

        cards = []
        for item in items:
            priority = str(item.get('priority', 'LOW')).upper()
            title    = str(item.get('title', 'Untitled'))
            desc     = str(item.get('description', ''))
            # Strip Mission Prompt block
            if '**Mission Prompt:**' in desc:
                desc = desc.split('**Mission Prompt:**')[0].strip()
            time_str = str(item.get('created_at', ''))[:10]

            cards.append(f'''<div class="cpo-item {priority}" onclick="toggleCpo(this)">
  <div class="cpo-item-header">
    <div class="cpo-item-title">{title}</div>
    <div class="cpo-item-meta">
      <span class="pri-badge {priority}">{priority}</span>
      <span style="font-size:.68rem;color:var(--muted)">{time_str}</span>
    </div>
  </div>
  <div class="cpo-item-desc">{desc}</div>
</div>''')

        sections_html.append(f'''<div class="cpo-category">
  <div class="cpo-cat-header">&#x1F4CC; {cat} <span style="color:var(--muted);font-weight:400">({len(items)})</span></div>
  {"".join(cards)}
</div>''')

    return f'''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4CB; Improvement Backlog</span>
    <span class="section-badge">{len(backlog_items)} items</span>
    <span class="section-line"></span>
  </div>
  <p style="color:var(--muted);font-size:.78rem;margin-bottom:12px">Klik op een item om de volledige beschrijving te tonen.</p>
  {"".join(sections_html)}
</div>'''


def _build_llm_diagnostics(learning_data):
    """SwarmLearner diagnostics: bottleneck + funnel + LLM summary."""
    if not learning_data:
        return '''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F52C; LLM Diagnostics</span>
    <span class="section-line"></span>
  </div>
  <p style="color:var(--muted)">SwarmLearner heeft nog niet gedraaid (elke 20 cycles).</p>
</div>'''

    timestamp = str(learning_data.get('timestamp', ''))[:19].replace('T', ' ')
    total     = learning_data.get('total_decisions', 0)
    funnel    = learning_data.get('funnel', {})
    score_pass = funnel.get('score_pass', 0)
    build_case = funnel.get('build_case', 0)
    executed   = funnel.get('executed', 0)
    near_miss  = learning_data.get('near_miss_count', 0)
    bottleneck = str(learning_data.get('bottleneck_gate', 'unknown')).lower()
    llm_summary = str(learning_data.get('llm_summary', 'No diagnosis available.'))
    current_threshold = _safe_float(learning_data.get('current_threshold', 0.40))

    score_pass_rate = f"{score_pass / total * 100:.1f}%" if total else 'N/A'
    build_case_rate = f"{build_case / total * 100:.1f}%" if total else 'N/A'

    # Bottleneck banner
    if bottleneck in ('execution', 'execution_gate'):
        bn_color, bn_bg, bn_border, bn_icon, bn_label = 'var(--red)', 'rgba(239,68,68,0.12)', 'rgba(239,68,68,0.4)', '&#x1F6A8;', 'EXECUTION GATE'
    elif 'llm' in bottleneck or 'build_case' in bottleneck:
        bn_color, bn_bg, bn_border, bn_icon, bn_label = 'var(--yellow)', 'rgba(245,158,11,0.12)', 'rgba(245,158,11,0.4)', '&#x26A0;&#xFE0F;', 'LLM BUILD_CASE'
    elif 'score' in bottleneck:
        bn_color, bn_bg, bn_border, bn_icon, bn_label = 'var(--yellow)', 'rgba(245,158,11,0.08)', 'rgba(245,158,11,0.3)', '&#x26A0;&#xFE0F;', 'SCORE THRESHOLD'
    else:
        bn_color, bn_bg, bn_border, bn_icon, bn_label = 'var(--blue)', 'rgba(59,130,246,0.08)', 'rgba(59,130,246,0.3)', '&#x1F50D;', bottleneck.upper() or 'UNKNOWN'

    exec_color = 'var(--red)' if executed == 0 else 'var(--green)'

    return f'''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F52C; LLM Diagnostics</span>
    <span style="font-size:.75rem;color:var(--muted)">Updated: {timestamp} &bull; Every 20 cycles</span>
    <span class="section-line"></span>
  </div>

  <div style="padding:14px 18px;background:{bn_bg};border:1px solid {bn_border};border-radius:10px;margin-bottom:16px;display:flex;align-items:center;gap:12px">
    <span style="font-size:1.6rem">{bn_icon}</span>
    <div>
      <div style="font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Bottleneck</div>
      <div style="font-size:1.2rem;font-weight:700;color:{bn_color}">{bn_label}</div>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px">
    <div class="mstat"><div class="big" style="color:var(--blue)">{score_pass_rate}</div><div class="lbl">Score Pass (&ge;{current_threshold})</div></div>
    <div class="mstat"><div class="big" style="color:var(--purple)">{build_case_rate}</div><div class="lbl">BUILD_CASE Rate</div></div>
    <div class="mstat"><div class="big" style="color:var(--yellow)">{near_miss}</div><div class="lbl">Near-Miss</div></div>
    <div class="mstat"><div class="big" style="color:{exec_color}">{executed}</div><div class="lbl">Executed</div></div>
  </div>

  <div style="background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px">
    <div style="font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">LLM Diagnosis</div>
    <div style="font-size:.88rem;line-height:1.55;color:var(--text)">{llm_summary}</div>
  </div>
</div>'''


def _build_llm_cost_section(llm_stats):
    """LLM cost monitor with per-type breakdown."""
    if not llm_stats or not llm_stats.get('by_agent'):
        return ''

    today_total  = llm_stats.get('today_total', 0)
    hourly_total = llm_stats.get('hourly_total', 0)
    by_agent     = llm_stats.get('by_agent', {})

    hour_color = 'var(--red)' if hourly_total > 100_000 else ('var(--yellow)' if hourly_total > 50_000 else 'var(--green)')

    rows = ''
    for agent, stats in sorted(by_agent.items(), key=lambda x: x[1].get('today', 0), reverse=True):
        tok_today = stats.get('today', 0)
        tok_hour  = stats.get('hour', 0)
        calls     = stats.get('calls_today', 0)
        if tok_today == 0 and calls == 0:
            continue
        hc = 'var(--red)' if tok_hour > 100_000 else ('var(--yellow)' if tok_hour > 50_000 else 'var(--muted)')
        rows += f'''<tr>
            <td style="padding:5px 8px;font-weight:500">{agent}</td>
            <td style="padding:5px 8px;text-align:right">{tok_today:,}</td>
            <td style="padding:5px 8px;text-align:right;color:{hc}">{tok_hour:,}</td>
            <td style="padding:5px 8px;text-align:right">{calls}</td>
        </tr>'''

    if not rows:
        return ''

    return f'''<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4B8; LLM Cost Monitor</span>
    <span class="section-badge">Today: {today_total:,} tokens</span>
    <span style="margin-left:auto;font-size:.8rem;color:{hour_color}">Hour: {hourly_total:,}</span>
    <span class="section-line"></span>
  </div>
  <div style="overflow-x:auto">
  <table style="width:100%;border-collapse:collapse;font-size:.83rem">
    <thead><tr style="border-bottom:1px solid var(--border);color:var(--muted)">
      <th style="padding:5px 8px;text-align:left">Agent</th>
      <th style="padding:5px 8px;text-align:right">Tokens Today</th>
      <th style="padding:5px 8px;text-align:right">Tokens/Hour</th>
      <th style="padding:5px 8px;text-align:right">Calls Today</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
  <div style="font-size:.72rem;color:var(--muted);margin-top:8px">
    Pricing: Input $0.15/M &bull; Output $0.60/M &bull; Thinking $3.50/M (Gemini 2.5 Flash)
  </div>
</div>'''


def build_tab_intelligence(backlog_items, learning_data, llm_stats):
    return (
        _build_backlog_section(backlog_items)
        + _build_llm_diagnostics(learning_data)
        + _build_llm_cost_section(llm_stats)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4 — Trades (compacter charts: 180px)
# ─────────────────────────────────────────────────────────────────────────────

def _build_trades_charts(trades, pnl_snapshots):
    """P&L charts at 180px height."""
    from collections import defaultdict
    daily_pnl = defaultdict(float)
    for t in trades:
        if not _is_closed(t):
            continue
        pnl = _safe_float(t.get('pnl'))
        exit_time = t.get('exit_time') or ''
        try:
            day = datetime.fromisoformat(str(exit_time).replace('Z', '+00:00')).strftime('%Y-%m-%d')
            daily_pnl[day] += pnl
        except Exception:
            pass

    today = date.today()
    days  = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    vals  = [round(daily_pnl.get(d, 0), 2) for d in days]
    short_days = [d[5:] for d in days]
    bar_colors = ['rgba(16,185,129,0.7)' if v >= 0 else 'rgba(239,68,68,0.7)' for v in vals]

    # Cumulative
    cum = []
    run = 0.0
    for v in vals:
        run += v
        cum.append(round(run, 2))

    parts = []

    if any(v != 0 for v in vals):
        parts.append(f'''
<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px">
  <div style="font-size:.72rem;font-weight:600;color:var(--muted);text-transform:uppercase;margin-bottom:10px">Daily Realized P&amp;L — last 30 days</div>
  <div style="position:relative;height:180px"><canvas id="v2chartDaily"></canvas></div>
</div>
<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px">
  <div style="font-size:.72rem;font-weight:600;color:var(--muted);text-transform:uppercase;margin-bottom:10px">Cumulative Realized P&amp;L</div>
  <div style="position:relative;height:140px"><canvas id="v2chartCumul"></canvas></div>
</div>
<script>
new Chart(document.getElementById('v2chartDaily'), {{
    type: 'bar',
    data: {{
        labels: {json.dumps(short_days)},
        datasets: [{{ label: 'P&L', data: {json.dumps(vals)}, backgroundColor: {json.dumps(bar_colors)}, borderRadius: 3 }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ ticks: {{ color: '#9ca3af', font: {{ size: 9 }}, maxRotation: 45 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
            y: {{ ticks: {{ color: '#9ca3af', font: {{ size: 9 }}, callback: v => '$' + v.toFixed(0) }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
        }}
    }}
}});
new Chart(document.getElementById('v2chartCumul'), {{
    type: 'line',
    data: {{
        labels: {json.dumps(short_days)},
        datasets: [{{ label: 'Cumulative', data: {json.dumps(cum)}, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.08)', fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ ticks: {{ color: '#9ca3af', font: {{ size: 9 }}, maxRotation: 45 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
            y: {{ ticks: {{ color: '#9ca3af', font: {{ size: 9 }}, callback: v => '$' + v.toFixed(0) }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
        }}
    }}
}});
</script>''')

    if pnl_snapshots:
        snap_days = [s['date'][5:] for s in pnl_snapshots[-30:]]
        snap_vals = [s.get('unrealized_pnl', 0) for s in pnl_snapshots[-30:]]
        snap_colors = ['rgba(59,130,246,0.7)' if v >= 0 else 'rgba(239,68,68,0.7)' for v in snap_vals]
        parts.append(f'''
<div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;margin-bottom:16px">
  <div style="font-size:.72rem;font-weight:600;color:var(--muted);text-transform:uppercase;margin-bottom:10px">Unrealized P&amp;L — Daily Snapshot</div>
  <div style="position:relative;height:160px"><canvas id="v2chartUnreal"></canvas></div>
</div>
<script>
new Chart(document.getElementById('v2chartUnreal'), {{
    type: 'bar',
    data: {{
        labels: {json.dumps(snap_days)},
        datasets: [{{ label: 'Unrealized P&L', data: {json.dumps(snap_vals)}, backgroundColor: {json.dumps(snap_colors)}, borderRadius: 3 }}]
    }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ display: false }} }},
        scales: {{
            x: {{ ticks: {{ color: '#9ca3af', font: {{ size: 9 }}, maxRotation: 45 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
            y: {{ ticks: {{ color: '#9ca3af', font: {{ size: 9 }}, callback: v => '$' + v.toFixed(0) }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
        }}
    }}
}});
</script>''')

    return '\n'.join(parts)


def _build_trade_history_table(trades):
    """Closed trade history with pagination."""
    closed = sorted([t for t in trades if _is_closed(t)], key=_ts, reverse=True)
    if not closed:
        return '<p style="color:var(--muted)">Geen afgesloten trades.</p>'

    # Stats bar
    total_pnl = sum(_safe_float(t.get('pnl')) for t in closed)
    wins = sum(1 for t in closed if _safe_float(t.get('pnl')) > 0)
    wr   = wins / len(closed) * 100 if closed else 0
    pnl_color = 'var(--green)' if total_pnl >= 0 else 'var(--red)'
    sign = '+' if total_pnl >= 0 else ''
    stats = f'''<div style="display:flex;gap:28px;flex-wrap:wrap;padding:8px 0 16px">
      <div><div style="color:var(--muted);font-size:.72rem">TOTAL P&amp;L</div><div style="font-weight:700;color:{pnl_color}">{sign}${total_pnl:.2f}</div></div>
      <div><div style="color:var(--muted);font-size:.72rem">WIN RATE</div><div style="font-weight:700">{wr:.0f}%</div></div>
      <div><div style="color:var(--muted);font-size:.72rem">CLOSED TRADES</div><div style="font-weight:700">{len(closed)}</div></div>
    </div>'''

    TH = '<th>'
    rows = []
    for t in closed:
        ticker     = t.get('ticker', '?')
        action     = (t.get('action') or 'BUY').upper()
        direction  = 'LONG' if action == 'BUY' else 'SHORT'
        dir_color  = 'var(--green)' if action == 'BUY' else 'var(--red)'
        tf         = t.get('timeframe', '—')
        entry      = _safe_float(t.get('entry_price') or t.get('intended_price'))
        exit_price = _safe_float(t.get('exit_price'))
        pnl        = _safe_float(t.get('pnl'))
        pnl_pct    = _safe_float(t.get('pnl_pct'))
        pnl_color  = 'var(--green)' if pnl > 0 else ('var(--red)' if pnl < 0 else 'var(--muted)')
        pnl_sign   = '+' if pnl > 0 else ''

        entry_ts = _safe_float(t.get('entry_time'))
        exit_ts  = t.get('exit_time', 0)
        duration = '—'
        try:
            if isinstance(exit_ts, str):
                exit_ts = datetime.fromisoformat(exit_ts).timestamp()
            if entry_ts and exit_ts:
                secs = int(float(exit_ts) - float(entry_ts))
                duration = f"{secs // 3600}h {(secs % 3600) // 60}m" if secs >= 3600 else f"{secs // 60}m"
        except Exception:
            pass

        pg = len(rows) // 20
        display = 'table-row' if pg == 0 else 'none'
        exit_html = f'${exit_price:.4f}' if exit_price else '—'
        rows.append(f'''<tr class="v2hist-row" data-pg="{pg}" style="display:{display}">
            <td style="font-weight:600">{ticker}</td>
            <td style="color:var(--muted)">{tf}</td>
            <td><span style="color:{dir_color}">{direction}</span></td>
            <td>${entry:.4f}</td>
            <td>{exit_html}</td>
            <td style="color:{pnl_color};font-weight:600">{pnl_sign}${pnl:.2f}</td>
            <td style="color:{pnl_color}">{pnl_sign}{pnl_pct:.1f}%</td>
            <td style="color:var(--muted)">{duration}</td>
        </tr>''')

    total_rows  = len(rows)
    total_pages = max(1, (total_rows + 19) // 20)

    js = f'''<script>
(function(){{
  var cur=0, total={total_pages};
  function show(p){{
    cur=p;
    document.querySelectorAll('#v2hist-tbody .v2hist-row').forEach(function(r){{
      r.style.display=(parseInt(r.dataset.pg)===p)?'table-row':'none';
    }});
    document.getElementById('v2hist-info').textContent='Pagina '+(p+1)+' van '+total;
    document.getElementById('v2hist-prev').disabled=(p===0);
    document.getElementById('v2hist-next').disabled=(p===total-1);
  }}
  document.getElementById('v2hist-prev').addEventListener('click',function(){{if(cur>0)show(cur-1);}});
  document.getElementById('v2hist-next').addEventListener('click',function(){{if(cur<total-1)show(cur+1);}});
  show(0);
}})();
</script>'''

    return f'''{stats}
<div style="overflow-x:auto">
<table class="data-table">
  <thead><tr>{TH}Ticker</th>{TH}TF</th>{TH}Dir</th>{TH}Entry</th>{TH}Exit</th>{TH}P&amp;L</th>{TH}P&amp;L %</th>{TH}Duration</th></tr></thead>
  <tbody id="v2hist-tbody">{"".join(rows)}</tbody>
</table>
</div>
<div style="display:flex;align-items:center;gap:12px;padding:10px 0 2px">
  <button id="v2hist-prev" class="pg-btn">&#8592; Vorige</button>
  <span id="v2hist-info" style="color:var(--muted);font-size:.82rem"></span>
  <button id="v2hist-next" class="pg-btn">Volgende &#8594;</button>
</div>
{js}'''


def build_tab_trades(trades, positions_status, pnl_snapshots):
    charts   = _build_trades_charts(trades, pnl_snapshots)
    history  = _build_trade_history_table(trades)
    pos_html = _build_open_positions(trades, positions_status)

    return f'''{pos_html}
<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4C8; P&amp;L Charts</span>
    <span class="section-line"></span>
  </div>
  {charts if charts else '<p style="color:var(--muted)">Geen trade data voor charts.</p>'}
</div>
<div class="section">
  <div class="section-header">
    <span class="section-title">&#x1F4DC; Trade History</span>
    <span class="section-badge">{sum(1 for t in trades if _is_closed(t))} trades</span>
    <span class="section-line"></span>
  </div>
  {history}
</div>'''


# ─────────────────────────────────────────────────────────────────────────────
# Tab 5 — RSI (verbatim from original dashboard_server.py)
# ─────────────────────────────────────────────────────────────────────────────

def build_tab_rsi():
    """Import and call the original RSI section builder."""
    try:
        from utils.dashboard_server import _build_rsi_section
        return _build_rsi_section()
    except Exception as e:
        logger.warning(f'Could not import RSI section from v1: {e}')
        return '<div style="color:var(--muted);padding:24px">RSI tab unavailable — zie origineel dashboard.</div>'


# ─────────────────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────────────────

def build_v2_html(agents, backlog_items, trades, positions_status, learning_data, llm_stats, pnl_snapshots):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # Thematic Exposure is a separate sleeve with its own dashboard (/thematic-exposure) —
    # keep it out of the main Overview/Trades tabs.
    trades = [t for t in (trades or []) if not t.get('thematic_exposure')]
    return (
        _HTML_SHELL
        .replace('{css}', _CSS)
        .replace('{timestamp}', now)
        .replace('{tab_overview}',     build_tab_overview(agents, trades, positions_status, pnl_snapshots))
        .replace('{tab_decisions}',    build_tab_decisions())
        .replace('{tab_intelligence}', build_tab_intelligence(backlog_items, learning_data, llm_stats))
        .replace('{tab_trades}',       build_tab_trades(trades, positions_status, pnl_snapshots))
        .replace('{tab_rsi}',          build_tab_rsi())
    )
