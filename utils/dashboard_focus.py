"""
Focused dashboard — strips the default view down to what the operator needs
during the profit-recovery plan:
  1) Health      — status, last cycle, balance, drawdown, free margin
  2) Open pos    — per-trade stage, unrealized PnL, SL/TP
  3) Phase 1     — exit-geometry KPIs since 2026-04-21 18:00 UTC
  4) Phase 3     — funnel throughput since loose-mode deploy
  5) Plan status — phase flags + deferred backlog reminder

Serves at /focus on the existing dashboard server.
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone


PHASE1_DEPLOY_TS = datetime(2026, 4, 21, 18, 0, tzinfo=timezone.utc).timestamp()
PHASE3_DEPLOY_TS = datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc).timestamp()


def _parse_ts(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0
    return 0.0


def _load_json(path: str, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _read_balance_snapshot() -> dict:
    """Pull balance/peak/DD from known state files. Best-effort."""
    peak = _load_json("portfolio_peak.json", {})
    pnl_snap = _load_json("pnl_snapshots.json", [])

    peak_equity = float(peak.get("peak_equity", 0) or 0)
    balance = 0.0
    unrealized = 0.0

    if isinstance(pnl_snap, list) and pnl_snap:
        unrealized = float(pnl_snap[-1].get("unrealized_pnl", 0) or 0)

    # Exchange balance isn't in a JSON file we can trust (only live via HL client).
    # Fallback: peak - |DD| is unknown without live, so we just show peak + unreal.
    return {
        "peak_equity": peak_equity,
        "balance": balance,
        "unrealized": unrealized,
    }


def _collect_trades() -> list:
    t = _load_json("trade_log.json", [])
    if isinstance(t, dict):
        t = list(t.values())
    if not isinstance(t, list):
        t = []
    return t


def _phase1_stats(trades: list) -> dict:
    closed = [
        t for t in trades
        if t.get("status") == "CLOSED"
        and _parse_ts(t.get("exit_time") or t.get("close_time")) >= PHASE1_DEPLOY_TS
    ]
    wins = [float(t.get("pnl") or 0) for t in closed if (t.get("pnl") or 0) > 0]
    losses = [abs(float(t.get("pnl") or 0)) for t in closed if (t.get("pnl") or 0) < 0]
    pf = (sum(wins) / sum(losses)) if losses else (float("inf") if wins else 0.0)
    stage1_plus = sum(
        1 for t in closed
        if (t.get("sl_stage") or 0) >= 1 or t.get("partial_tp1_taken")
    )
    stage0 = sum(1 for t in closed if (t.get("sl_stage") or 0) == 0)
    total_pnl = sum(float(t.get("pnl") or 0) for t in closed)
    n = len(closed)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "pf": pf,
        "stage1_rate": (stage1_plus / n * 100) if n else 0.0,
        "stage0_rate": (stage0 / n * 100) if n else 0.0,
        "total_pnl": total_pnl,
    }


def _phase3_funnel(decisions: list) -> dict:
    post = [d for d in decisions if _parse_ts(d.get("timestamp", "")) >= PHASE3_DEPLOY_TS]
    if not post:
        return {"n": 0, "by_decision": {}, "conviction_dropped": 0}
    by = {}
    for d in post:
        k = d.get("decision") or d.get("next_step") or "UNKNOWN"
        by[k] = by.get(k, 0) + 1
    return {
        "n": len(post),
        "by_decision": by,
        "build_case": by.get("BUILD_CASE", 0) + by.get("GO", 0),
        "no_go": by.get("NO_GO", 0) + by.get("REJECTED", 0),
    }


def _open_positions(trades: list) -> list:
    return [t for t in trades if t.get("status") == "OPEN"]


def _close_reason_breakdown(trades: list, since_ts: float) -> list:
    closed = [
        t for t in trades
        if t.get("status") == "CLOSED"
        and _parse_ts(t.get("exit_time") or t.get("close_time")) >= since_ts
    ]
    by = {}
    for t in closed:
        r = t.get("close_reason") or "UNKNOWN"
        by.setdefault(r, []).append(float(t.get("pnl") or 0))
    out = [
        {"reason": r, "n": len(p), "wins": sum(1 for x in p if x > 0), "pnl": sum(p)}
        for r, p in by.items()
    ]
    out.sort(key=lambda x: -x["n"])
    return out


def _fmt_age(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc).timestamp() - dt.timestamp()
        if age < 60:
            return f"{int(age)}s ago"
        if age < 3600:
            return f"{int(age/60)}m ago"
        return f"{age/3600:.1f}h ago"
    except Exception:
        return "?"


def build_focus_html() -> str:
    dash = _load_json("dashboard.json", {})
    trades = _collect_trades()
    decisions = _load_json("decision_history.json", [])
    bal = _read_balance_snapshot()

    p1 = _phase1_stats(trades)
    p3 = _phase3_funnel(decisions)
    opens = _open_positions(trades)
    close_reasons = _close_reason_breakdown(trades, PHASE1_DEPLOY_TS)

    status = dash.get("status", "?")
    last_update = dash.get("last_update", "")
    cycle_n = dash.get("cycle_count", "?")
    cycle_t = dash.get("cycle_time_sec", "?")

    status_color = {"ACTIVE": "#2ecc71", "IDLE": "#f39c12", "ERROR": "#e74c3c"}.get(status, "#95a5a6")
    pf_color = "#2ecc71" if p1["pf"] >= 1.0 else ("#f39c12" if p1["pf"] >= 0.7 else "#e74c3c")
    s1_color = "#2ecc71" if p1["stage1_rate"] >= 20 else "#f39c12"
    s0_color = "#2ecc71" if p1["stage0_rate"] <= 55 else "#e74c3c"

    def pf_str(v):
        if v == float("inf"):
            return "∞"
        return f"{v:.2f}"

    open_rows = ""
    if opens:
        for t in opens:
            sym = html.escape(str(t.get("symbol") or t.get("ticker") or "?"))
            action = html.escape(str(t.get("action", "?")))
            stage = int(t.get("sl_stage") or 0)
            stage_lbl = {0: "stage 0 (initial SL)", 1: "stage 1 (BE)", 2: "stage 2 (trailing)"}.get(stage, f"stage {stage}")
            stage_col = ["#e74c3c", "#f39c12", "#2ecc71"][min(stage, 2)]
            entry = float(t.get("entry_price") or 0)
            sl = float(t.get("stop_loss") or 0)
            tp = float(t.get("take_profit") or 0)
            upnl = t.get("unrealized_pnl")
            upnl_str = f"${float(upnl):+.2f}" if upnl is not None else "—"
            partial = "✓" if t.get("partial_tp1_taken") else "—"
            open_rows += f"""
              <tr>
                <td><b>{sym}</b></td>
                <td>{action}</td>
                <td style="color:{stage_col}">{stage_lbl}</td>
                <td>{entry:.4f}</td>
                <td>{sl:.4f}</td>
                <td>{tp:.4f}</td>
                <td>{partial}</td>
                <td>{upnl_str}</td>
              </tr>"""
    else:
        open_rows = '<tr><td colspan="8" style="text-align:center;color:#888">no open positions</td></tr>'

    close_rows = ""
    if close_reasons:
        for r in close_reasons[:8]:
            pnl_col = "#2ecc71" if r["pnl"] >= 0 else "#e74c3c"
            close_rows += f"""
              <tr>
                <td>{html.escape(r['reason'])}</td>
                <td>{r['n']}</td>
                <td>{r['wins']}</td>
                <td style="color:{pnl_col}">${r['pnl']:+.2f}</td>
              </tr>"""
    else:
        close_rows = '<tr><td colspan="4" style="text-align:center;color:#888">no closes since Phase 1 deploy</td></tr>'

    funnel_rows = ""
    for k, v in sorted(p3.get("by_decision", {}).items(), key=lambda x: -x[1]):
        funnel_rows += f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>"
    if not funnel_rows:
        funnel_rows = '<tr><td colspan="2" style="text-align:center;color:#888">no decisions logged yet</td></tr>'

    return f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1a1d23">
<meta http-equiv="refresh" content="60">
<title>Swarm Focus</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; background:#1a1d23; color:#e8e8e8; margin:0; padding:20px; -webkit-text-size-adjust:100%; }}
  h1 {{ margin:0 0 4px 0; font-size:22px; }}
  h2 {{ margin:0 0 12px 0; font-size:15px; color:#9aa5b1; text-transform:uppercase; letter-spacing:0.5px; font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(380px,1fr)); gap:16px; margin-top:20px; }}
  .card {{ background:#23272e; border-radius:8px; padding:18px; border:1px solid #2d333b; min-width:0; }}
  .kv {{ display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-bottom:1px solid #2d333b; }}
  .kv:last-child {{ border-bottom:none; }}
  .kv .k {{ color:#9aa5b1; flex-shrink:0; }}
  .kv .v {{ font-weight:600; font-variant-numeric:tabular-nums; text-align:right; }}
  .table-wrap {{ overflow-x:auto; -webkit-overflow-scrolling:touch; margin:0 -4px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid #2d333b; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  th {{ color:#9aa5b1; font-weight:600; font-size:11px; text-transform:uppercase; }}
  .status-dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; background:{status_color}; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600; margin-right:4px; margin-bottom:4px; }}
  .phase-ok {{ background:#1e4620; color:#8fd89f; }}
  .phase-run {{ background:#3d3a18; color:#f0d97d; }}
  .phase-pend {{ background:#2d333b; color:#9aa5b1; }}
  .muted {{ color:#9aa5b1; font-size:12px; }}
  @media (max-width: 640px) {{
    body {{ padding:12px; }}
    h1 {{ font-size:18px; }}
    h2 {{ font-size:13px; }}
    .grid {{ grid-template-columns:1fr; gap:12px; margin-top:14px; }}
    .card {{ padding:14px; }}
    .kv {{ font-size:14px; }}
    table {{ font-size:12px; }}
    th, td {{ padding:5px 6px; }}
    .muted {{ font-size:11px; }}
  }}
</style>
</head><body>

<h1><span class="status-dot"></span>Swarm · {status}</h1>
<div class="muted">cycle #{cycle_n} · last update {_fmt_age(last_update)} · cycle time {cycle_t}s</div>

<div class="grid">

  <div class="card">
    <h2>Plan status</h2>
    <div style="line-height:1.9">
      <span class="badge phase-ok">Phase 0 · done</span>
      <span class="badge phase-ok">Phase 1 · done</span>
      <span class="badge phase-pend">Phase 2 · deferred</span>
      <span class="badge phase-run">Phase 3 · running</span>
    </div>
    <div class="muted" style="margin-top:10px">
      Phase 1: exit geometry (BE 15%/20%, profit-lock 50%, time-exit 72h/168h)<br>
      Phase 3: funnel loose (SETUP_MIN_CONVICTION 0.25/0.20/0.30), MAX_POSITION_PCT 0.10
    </div>
    <div class="muted" style="margin-top:10px; padding-top:10px; border-top:1px solid #2d333b">
      <b>Backlog:</b> limit-order entry on swing/fib retest — revisit after 20-30 closed trades
    </div>
  </div>

  <div class="card">
    <h2>Health</h2>
    <div class="kv"><span class="k">peak equity</span><span class="v">${bal['peak_equity']:.2f}</span></div>
    <div class="kv"><span class="k">unrealized pnl (today)</span><span class="v">${bal['unrealized']:+.2f}</span></div>
    <div class="kv"><span class="k">open positions</span><span class="v">{len(opens)}</span></div>
    <div class="kv"><span class="k">cycle time</span><span class="v">{cycle_t}s</span></div>
    <div class="muted" style="margin-top:10px">live balance + free margin require exchange call — check via <code>/diag balance</code></div>
  </div>

  <div class="card" style="grid-column: 1 / -1;">
    <h2>Open positions</h2>
    <div class="table-wrap"><table>
      <tr><th>ticker</th><th>dir</th><th>stage</th><th>entry</th><th>SL</th><th>TP</th><th>partial</th><th>unreal PnL</th></tr>
      {open_rows}
    </table></div>
  </div>

  <div class="card">
    <h2>Phase 1 scorecard <span class="muted" style="font-weight:400">· since 21-04 18:00 UTC</span></h2>
    <div class="kv"><span class="k">closed trades</span><span class="v">{p1['n']}</span></div>
    <div class="kv"><span class="k">wins / losses</span><span class="v">{p1['wins']} / {p1['losses']}</span></div>
    <div class="kv"><span class="k">profit factor</span><span class="v" style="color:{pf_color}">{pf_str(p1['pf'])} <span class="muted">(target ≥ 1.0)</span></span></div>
    <div class="kv"><span class="k">stage 1+ reach</span><span class="v" style="color:{s1_color}">{p1['stage1_rate']:.0f}% <span class="muted">(target ≥ 20%)</span></span></div>
    <div class="kv"><span class="k">stage 0 close</span><span class="v" style="color:{s0_color}">{p1['stage0_rate']:.0f}% <span class="muted">(target ≤ 55%)</span></span></div>
    <div class="kv"><span class="k">total pnl</span><span class="v">${p1['total_pnl']:+.2f}</span></div>
  </div>

  <div class="card">
    <h2>Phase 3 funnel <span class="muted" style="font-weight:400">· since 24-04 08:00 UTC</span></h2>
    <div class="kv"><span class="k">decisions logged</span><span class="v">{p3['n']}</span></div>
    <div class="kv"><span class="k">BUILD_CASE passes</span><span class="v">{p3.get('build_case', 0)}</span></div>
    <div class="kv"><span class="k">NO_GO</span><span class="v">{p3.get('no_go', 0)}</span></div>
    <div class="table-wrap" style="margin-top:10px"><table>
      <tr><th>decision</th><th>count</th></tr>
      {funnel_rows}
    </table></div>
  </div>

  <div class="card" style="grid-column: 1 / -1;">
    <h2>Close reasons <span class="muted" style="font-weight:400">· since Phase 1 deploy</span></h2>
    <div class="table-wrap"><table>
      <tr><th>reason</th><th>n</th><th>wins</th><th>total pnl</th></tr>
      {close_rows}
    </table></div>
  </div>

</div>

<div class="muted" style="margin-top:20px; text-align:center">auto-refresh every 60s · full dashboard at <a href="/" style="color:#8fd89f">/</a></div>

</body></html>
"""
