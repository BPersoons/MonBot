"""
Performance dashboard — served at /performance.

Answers two questions at a glance:
1. Is the system getting better or worse over time?
2. Where is the bottleneck in the pipeline right now?

Single scrollable page, no tabs. All data derived from existing JSON state files.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone


# ── Data helpers (same pattern as dashboard_focus.py) ────────────────────────

def _load_json(path: str, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def _parse_ts(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            s = v.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0
    return 0.0


def _collect_closed_trades(raw) -> list:
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return []
    closed = [
        t for t in raw
        if isinstance(t, dict)
        and t.get("status") == "CLOSED"
        and t.get("pnl") is not None
    ]
    closed.sort(key=lambda t: _parse_ts(t.get("exit_time") or t.get("close_time") or 0))
    return closed


def _ts_to_date(ts: float) -> str:
    try:
        return datetime.utcfromtimestamp(ts).strftime("%m-%d")
    except Exception:
        return "?"


# ── Computation layer ─────────────────────────────────────────────────────────

def _compute_trade_metrics(closed: list) -> dict:
    n = len(closed)
    if n == 0:
        return {"n": 0}

    pnls = [float(t.get("pnl") or 0) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    wr = len(wins) / n * 100 if n else 0.0
    total_pnl = sum(pnls)
    pf = sum(wins) / sum(losses) if losses else (float("inf") if wins else 0.0)

    # Trend: last 50 vs prior 50 (or half/half if < 100)
    split = min(50, n // 2) if n < 100 else 50
    if split >= 5:
        prior = closed[:n - split]
        recent = closed[n - split:]
        prior_pnls = [float(t.get("pnl") or 0) for t in prior]
        recent_pnls = [float(t.get("pnl") or 0) for t in recent]
        prior_wr = sum(1 for p in prior_pnls if p > 0) / len(prior_pnls) * 100 if prior_pnls else 0
        recent_wr = sum(1 for p in recent_pnls if p > 0) / len(recent_pnls) * 100 if recent_pnls else 0
        wr_delta = recent_wr - prior_wr
    else:
        wr_delta = 0.0
        recent_wr = wr
        prior_wr = wr

    if wr_delta > 2:
        trend_arrow, trend_color, trend_label = "▲", "var(--green)", "improving"
    elif wr_delta < -2:
        trend_arrow, trend_color, trend_label = "▼", "var(--red)", "declining"
    else:
        trend_arrow, trend_color, trend_label = "→", "var(--yellow)", "stable"

    # Cumulative P&L series
    cumul_labels, cumul_values = [], []
    running = 0.0
    for t in closed:
        running += float(t.get("pnl") or 0)
        ts = _parse_ts(t.get("exit_time") or t.get("close_time") or 0)
        cumul_labels.append(_ts_to_date(ts))
        cumul_values.append(round(running, 2))

    # Rolling 20-trade WR series
    rolling_labels, rolling_values = [], []
    if n >= 20:
        for i in range(20, n + 1):
            window = pnls[i - 20:i]
            rwr = sum(1 for p in window if p > 0) / 20 * 100
            ts = _parse_ts(closed[i - 1].get("exit_time") or closed[i - 1].get("close_time") or 0)
            rolling_labels.append(_ts_to_date(ts))
            rolling_values.append(round(rwr, 1))

    # SL stage stats
    sl_stages: dict = {0: [], 1: [], 2: []}
    for t in closed:
        stage = min(int(t.get("sl_stage") or 0), 2)
        sl_stages[stage].append(float(t.get("pnl") or 0))
    sl_stage_stats = {}
    for s, ps in sl_stages.items():
        key = str(s) if s < 2 else "2+"
        w = sum(1 for p in ps if p > 0)
        sl_stage_stats[key] = {
            "n": len(ps),
            "wins": w,
            "wr": round(w / len(ps) * 100, 1) if ps else 0.0,
            "pnl": round(sum(ps), 2),
        }

    # Direction stats (BUY=LONG, SELL=SHORT)
    dir_stats: dict = {"LONG": [], "SHORT": []}
    for t in closed:
        action = t.get("action", "BUY")
        direction = t.get("direction") or ("LONG" if action == "BUY" else "SHORT")
        key = "LONG" if direction in ("LONG", "BUY") else "SHORT"
        dir_stats[key].append(float(t.get("pnl") or 0))
    direction_stats = {}
    for d, ps in dir_stats.items():
        w = sum(1 for p in ps if p > 0)
        direction_stats[d] = {
            "n": len(ps),
            "wins": w,
            "wr": round(w / len(ps) * 100, 1) if ps else 0.0,
            "pnl": round(sum(ps), 2),
        }

    # Close reason breakdown
    close_reasons: dict = defaultdict(list)
    for t in closed:
        r = t.get("close_reason") or "UNKNOWN"
        close_reasons[r].append(float(t.get("pnl") or 0))
    close_reason_stats = sorted(
        [{"reason": r, "n": len(ps), "wins": sum(1 for p in ps if p > 0), "pnl": round(sum(ps), 2)}
         for r, ps in close_reasons.items()],
        key=lambda x: -x["n"]
    )

    # Conviction buckets
    conv_buckets: dict = {"low": [], "mid": [], "high": []}
    for t in closed:
        conv = float(t.get("conviction") or 0)
        if conv == 0:
            continue
        if conv < 0.3:
            conv_buckets["low"].append(float(t.get("pnl") or 0))
        elif conv < 0.5:
            conv_buckets["mid"].append(float(t.get("pnl") or 0))
        else:
            conv_buckets["high"].append(float(t.get("pnl") or 0))
    conviction_stats = {}
    for b, ps in conv_buckets.items():
        w = sum(1 for p in ps if p > 0)
        conviction_stats[b] = {
            "n": len(ps),
            "wr": round(w / len(ps) * 100, 1) if ps else 0.0,
            "pnl": round(sum(ps), 2),
        }

    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(wr, 1),
        "total_pnl": round(total_pnl, 2),
        "pf": round(pf, 2) if pf != float("inf") else "∞",
        "wr_delta": round(wr_delta, 1),
        "recent_wr": round(recent_wr, 1),
        "prior_wr": round(prior_wr, 1),
        "trend_arrow": trend_arrow,
        "trend_color": trend_color,
        "trend_label": trend_label,
        "split": split,
        "cumul_labels": cumul_labels,
        "cumul_values": cumul_values,
        "rolling_labels": rolling_labels,
        "rolling_values": rolling_values,
        "sl_stage_stats": sl_stage_stats,
        "direction_stats": direction_stats,
        "close_reason_stats": close_reason_stats,
        "conviction_stats": conviction_stats,
    }


def _compute_funnel_metrics(learning: dict, decisions: list) -> dict:
    funnel = learning.get("funnel", {})
    ind = learning.get("indicator_bottleneck", {})
    avg_scores = ind.get("avg_scores", {})

    total = funnel.get("total_analyzed", 0)
    passed_score = funnel.get("passed_score_threshold", 0)
    build_case = funnel.get("llm_build_case", 0)
    executed = funnel.get("executed", 0)
    bottleneck_gate = funnel.get("bottleneck_gate", "")
    bottleneck_pct = funnel.get("bottleneck_pct", "")

    # Daily BUILD_CASE rate from decision_history (last 14 days)
    daily: dict = defaultdict(lambda: {"total": 0, "build_case": 0})
    for d in decisions:
        ts = _parse_ts(d.get("timestamp", ""))
        if ts == 0:
            continue
        dt = datetime.utcfromtimestamp(ts)
        day_key = dt.strftime("%m-%d")
        daily[day_key]["total"] += 1
        decision = (d.get("decision") or d.get("next_step") or "").upper()
        if decision in ("BUILD_CASE", "GO"):
            daily[day_key]["build_case"] += 1

    # Keep last 14 days, sorted
    sorted_days = sorted(daily.keys())[-14:]
    daily_labels = sorted_days
    daily_bc_counts = [daily[d]["build_case"] for d in sorted_days]
    daily_nogo_counts = [max(0, daily[d]["total"] - daily[d]["build_case"]) for d in sorted_days]
    daily_bc_pct = [
        round(daily[d]["build_case"] / daily[d]["total"] * 100, 1) if daily[d]["total"] else 0
        for d in sorted_days
    ]

    return {
        "total": total,
        "passed_score": passed_score,
        "build_case": build_case,
        "executed": executed,
        "bottleneck_gate": bottleneck_gate,
        "bottleneck_pct": bottleneck_pct,
        "avg_tech": round(avg_scores.get("tech", 0), 3),
        "avg_fund": round(avg_scores.get("fund", 0), 3),
        "avg_sent": round(avg_scores.get("sent", 0), 3),
        "lowest_contributor": ind.get("lowest_contributor", ""),
        "daily_labels": daily_labels,
        "daily_bc_counts": daily_bc_counts,
        "daily_nogo_counts": daily_nogo_counts,
        "daily_bc_pct": daily_bc_pct,
        "has_learning": bool(funnel),
    }


def _compute_param_history(auto_params: dict) -> dict:
    meta = auto_params.get("_meta", {})
    initial = auto_params.get("_initial", {})
    return {
        "score_threshold": auto_params.get("score_threshold", "—"),
        "initial_threshold": initial.get("score_threshold", "—"),
        "last_changed_at": meta.get("last_changed_at", ""),
        "change_reason": meta.get("change_reason", ""),
        "last_changed_by": meta.get("last_changed_by", ""),
    }


def _generate_advice(tm: dict, fm: dict, pm: dict) -> list:
    """
    Returns list of (severity, title, explanation) tuples.
    severity: "red" | "yellow" | "green"
    Rule-based, no LLM needed.
    """
    items = []
    n = tm.get("n", 0)
    wr = tm.get("wr", 0)
    wr_delta = tm.get("wr_delta", 0)
    sl_stages = tm.get("sl_stage_stats", {})
    dirs = tm.get("direction_stats", {})

    bottleneck = fm.get("bottleneck_gate", "")
    total = fm.get("total", 0)
    passed = fm.get("passed_score", 0)
    bc = fm.get("build_case", 0)
    executed_fm = fm.get("executed", 0)
    lowest = fm.get("lowest_contributor", "")
    avg_fund = fm.get("avg_fund", 0.0)
    avg_tech = fm.get("avg_tech", 0.0)
    score_pass_rate = passed / total * 100 if total else 0
    bc_rate = bc / total * 100 if total else 0

    short_n = dirs.get("SHORT", {}).get("n", 0)
    long_n = dirs.get("LONG", {}).get("n", 0)
    threshold = pm.get("score_threshold", "?")

    # ── Funnel bottleneck ─────────────────────────────────────────────────────
    if bottleneck == "score_threshold" and score_pass_rate < 8:
        items.append(("red", "Score gate blokkeert te veel kandidaten",
            f"Slechts {score_pass_rate:.1f}% haalt de algoritmische score gate (drempel: {threshold}). "
            f"Van {total} analyses zijn er {total - passed} al vóór de LLM weggefilterd. "
            "Wat te doen: wacht eerst 2–3 dagen op effect van de LLM-drempel fix (2026-05-19). "
            "Als daarna nog geen verbetering: verlaag score_threshold naar 0.20 in config/auto_params.json."))

    elif bottleneck == "llm_build_case" and bc_rate < 5:
        items.append(("yellow", "LLM geeft zelden BUILD_CASE — fix gedeployed, wacht op effect",
            f"Slechts {bc_rate:.1f}% van analyses leidt tot een uitgevoerde trade. "
            f"Van de {passed} die de score gate halen, geeft de LLM slechts {bc} keer groen licht. "
            "Oorzaak was een drempel-mismatch: LLM verwachtte score ≥ 0.50, maar scores van 0.25 werden doorgelaten. "
            "Fix gedeployed op 2026-05-19 (LLM-drempel verlaagd naar 0.38). "
            "Wacht 2–3 dagen — SwarmLearner update het rapport elk 20 cycles (~20 min)."))

    elif bottleneck == "execution" and bc > 5:
        exec_rate = executed_fm / bc * 100 if bc else 0
        if exec_rate < 70:
            items.append(("red", "Veel BUILD_CASEs worden geblokt vóór executie",
                f"Slechts {exec_rate:.0f}% van LLM BUILD_CASE leidt tot een echte order. "
                "Mogelijke oorzaken: RiskManager veto (regime gate, margin, positie caps), "
                "circuit breaker, of duplicaat-detectie. "
                "Wat te doen: check logs op [MACRO_GATE] of [RISK_VETO] regels. "
                "Gebruik /diag positions voor een live overzicht."))

    # ── Analyst scores ────────────────────────────────────────────────────────
    if lowest == "fund":
        if short_n > 0 and short_n >= long_n * 0.2:
            items.append(("green", "FA negatief door SHORT trades — normaal gedrag",
                f"FA scoort {avg_fund:+.3f} gemiddeld. "
                "Fundamentele analyse meet asset-kwaliteit en is altijd bullish gescoord. "
                "Bij SHORT-trades wordt FA geïnverteerd: goede fundamenten worden een negatieve bijdrage. "
                "Dit is correct — een asset met sterke fundamenten die technisch bearish is, is een valide SHORT. "
                "Geen actie nodig."))
        else:
            items.append(("yellow", "FA is laagste bijdrage — assets in pipeline hebben zwakke fundamenten",
                f"FA scoort {avg_fund:+.3f} gemiddeld over LONG-analyses. "
                "FA meet: TVL, marktadoptie, liquiditeit, on-chain activiteit. "
                "Negatieve score = de geanalyseerde assets zijn fundamenteel zwak. "
                "Wat te doen: dit is vaak 'wat het is' — de scanner pakt de meest liquide assets, "
                "niet de meest fundamenteel gezonde. Overweeg een minimum FA-score als extra filter "
                "als trades met negatieve FA consistent verliezen."))

    elif lowest == "tech" and avg_tech < 0.05:
        items.append(("yellow", "TA laagste bijdrage — markt geeft geen duidelijk signaal",
            f"TA scoort {avg_tech:+.3f} gemiddeld. "
            "TA meet prijspatronen (MACD, RSI, EMA, Bollinger, ADX, Stochastic, Volume). "
            "Score dicht bij 0 = rangebound markt zonder duidelijke trend. "
            "Wat te doen: niets aan te passen — dit is marktomstandigheid. "
            "De scanner promoted alleen assets met TA-score ≥ 0.12 (tech_prefilter_min), "
            "dus wat doorkomt heeft al enige directie."))

    # ── Win rate ──────────────────────────────────────────────────────────────
    if n >= 20:
        if wr_delta < -5:
            items.append(("red", f"Win Rate daalt snel ({wr_delta:+.1f}pp)",
                f"Recente WR: {tm.get('recent_wr')}% vs vorige periode: {tm.get('prior_wr')}%. "
                "Wat te doen: (1) check close reasons — als SL > 60% van closes, "
                "zijn entries te laat of SL te krap; "
                "(2) overweeg score_threshold tijdelijk te verhogen naar 0.30; "
                "(3) kijk naar SL stage tabel — als stage 0 domineert, bewegen trades niet in de goede richting."))
        elif wr < 30 and n >= 30:
            items.append(("red", f"Win Rate laag ({wr}%) — onder kritische grens",
                f"Baseline historisch: 34.8% over 233 trades. Huidige WR: {wr}% over {n} trades. "
                "Wat te doen: analyseer close reasons. Als STOP_LOSS > 60% van closes: "
                "entry-timing is het probleem (te laat in trend, SL te krap). "
                "Als TIME_EXIT dominant: trades bewegen in de goede richting maar niet snel genoeg — "
                "overweeg langere time_exit_hours of bredere TP."))
        elif wr_delta > 5:
            items.append(("green", f"Win Rate verbetert ({wr_delta:+.1f}pp) — overweeg opschalen",
                f"Recente WR: {tm.get('recent_wr')}% vs vorige: {tm.get('prior_wr')}%. "
                "Als dit trend doorzet: overweeg scan_universe_size te vergroten (momenteel {}) "
                "voor meer tradevolume, zodat de RSI-Auditor voldoende data krijgt om te tunen.".format(threshold)))

    # ── SHORT trades ──────────────────────────────────────────────────────────
    if short_n == 0 and n >= 10:
        items.append(("yellow", "Nog geen SHORT trades gegenereerd",
            "BTC-regime gate voor XYZ-assets is opgeheven (2026-05-19) en SHORT scoring is verbeterd. "
            "SHORT-trades vereisen: (1) Research Agent vindt backtest met short_pnl > long_pnl, "
            "(2) 4h SMA20 < SMA50 (momentum cross), (3) TA-score bearish. "
            "Als SHORT uitblijft: controleer of er assets zijn met voldoende SHORT-backtest historiek (≥2 trades)."))
    elif short_n > 0:
        short_wr = dirs.get("SHORT", {}).get("wr", 0)
        if short_wr < 25 and short_n >= 5:
            items.append(("red", f"SHORT Win Rate laag ({short_wr}%)",
                f"SHORT trades: {short_n} trades, {short_wr}% WR. "
                "SHORT is recent geactiveerd — mogelijke oorzaak: onvoldoende historiek voor goede selectie. "
                "Wat te doen: observeer nog 10 trades. Als WR onder 30% blijft: "
                "overweeg SHORT tijdelijk te beperken via score_threshold verhogen."))

    # ── SL stage ─────────────────────────────────────────────────────────────
    s0 = sl_stages.get("0", {})
    s0_wr = s0.get("wr", 0)
    s0_n = s0.get("n", 0)
    if s0_n >= 10 and s0_wr < 20:
        items.append(("yellow", f"Veel trades sluiten op initiële SL zonder progressie (stage 0: {s0_wr}% WR)",
            f"{s0_n} trades sloten op de originele SL. "
            "Dit betekent: de markt beweegt direct tégen de positie. "
            "Mogelijke oorzaken: (1) entry te laat (trend al uitgeput), "
            "(2) SL te krap — overweeg sl_pct_macro_max te verhogen van 3% naar 3.5% in auto_params.json, "
            "(3) verkeerd regime — zijn deze trades in bearish BTC-markt geplaatst?"))

    if not items:
        items.append(("green", "Geen urgente aandachtspunten",
            "Funnel werkt normaal en parameters zijn in orde. "
            "Observeer de BUILD_CASE rate en WR over de komende dagen."))

    return items


def _render_advice(items: list) -> str:
    COLOR_MAP = {
        "red": ("var(--red)", "rgba(239,68,68,0.08)", "rgba(239,68,68,0.3)", "🔴"),
        "yellow": ("var(--yellow)", "rgba(245,158,11,0.08)", "rgba(245,158,11,0.3)", "🟡"),
        "green": ("var(--green)", "rgba(16,185,129,0.08)", "rgba(16,185,129,0.3)", "🟢"),
    }
    cards = ""
    for severity, title, explanation in items:
        color, bg, border, icon = COLOR_MAP.get(severity, COLOR_MAP["yellow"])
        cards += f"""
        <div style="background:{bg};border:1px solid {border};border-radius:12px;padding:16px 20px;margin-bottom:12px">
          <div style="font-weight:700;font-size:.95rem;color:{color};margin-bottom:6px">{icon} {_html.escape(title)}</div>
          <div style="font-size:.82rem;color:var(--text);line-height:1.6">{_html.escape(explanation)}</div>
        </div>
        """
    return cards


# ── HTML section builders ─────────────────────────────────────────────────────

def _build_header(tm: dict, pm: dict) -> str:
    wr = tm.get("wr", "—")
    n = tm.get("n", 0)
    pf = tm.get("pf", "—")
    arrow = tm.get("trend_arrow", "→")
    color = tm.get("trend_color", "var(--yellow)")
    label = tm.get("trend_label", "stable")
    delta = tm.get("wr_delta", 0)
    split = tm.get("split", 50)
    recent_wr = tm.get("recent_wr", "—")
    prior_wr = tm.get("prior_wr", "—")
    total_pnl = tm.get("total_pnl", 0)
    pnl_color = "var(--green)" if isinstance(total_pnl, (int, float)) and total_pnl >= 0 else "var(--red)"

    kpi_cards = f"""
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:20px">
      <div class="card" style="text-align:center">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Win Rate</div>
        <div style="font-size:2.2rem;font-weight:700;color:var(--text)">{wr}%</div>
        <div style="font-size:.8rem;color:var(--muted);margin-top:4px">{n} closed trades</div>
        <div style="font-size:.8rem;color:{pnl_color};margin-top:4px">Total P&L: ${total_pnl:+.2f}</div>
      </div>
      <div class="card" style="text-align:center">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Profit Factor</div>
        <div style="font-size:2.2rem;font-weight:700;color:var(--text)">{pf}</div>
        <div style="font-size:.8rem;color:var(--muted);margin-top:4px">wins / losses (abs)</div>
        <div style="font-size:.8rem;color:var(--muted);margin-top:4px">&gt;1.0 = winstgevend</div>
      </div>
      <div class="card" style="text-align:center">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Trend (laatste {split} trades)</div>
        <div style="font-size:2.2rem;font-weight:700;color:{color}">{arrow} {delta:+.1f}pp</div>
        <div style="font-size:.8rem;color:{color};margin-top:4px;font-weight:600">{label}</div>
        <div style="font-size:.75rem;color:var(--muted);margin-top:4px">recent {recent_wr}% vs prior {prior_wr}%</div>
      </div>
    </div>
    """

    # Param callout
    reason = _html.escape(pm.get("change_reason", ""))
    changed_at = pm.get("last_changed_at", "")[:10]
    callout = ""
    if reason:
        callout = f"""
        <div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);border-radius:10px;padding:12px 16px;margin-bottom:24px;font-size:.8rem;color:var(--yellow);line-height:1.5">
          <span style="font-weight:700">Laatste param-wijziging ({changed_at}):</span> {reason[:200]}{'…' if len(reason) > 200 else ''}
        </div>
        """

    return kpi_cards + callout


def _build_timeseries(tm: dict) -> str:
    if not tm.get("n"):
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px">Nog geen closed trades beschikbaar.</div>'

    cumul_labels = json.dumps(tm["cumul_labels"])
    cumul_values = json.dumps(tm["cumul_values"])

    has_rolling = bool(tm.get("rolling_values"))
    rolling_labels = json.dumps(tm.get("rolling_labels", []))
    rolling_values = json.dumps(tm.get("rolling_values", []))
    n_rolling = len(tm.get("rolling_values", []))
    flat50 = json.dumps([50.0] * n_rolling)

    cumul_chart = f"""
    <div class="card">
      <div style="font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:16px">Cumulatieve P&L</div>
      <canvas id="chartCumul" height="200"></canvas>
    </div>
    <script>
    (function(){{
      var ctx = document.getElementById('chartCumul').getContext('2d');
      var vals = {cumul_values};
      var maxAbs = Math.max(...vals.map(Math.abs), 1);
      new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: {cumul_labels},
          datasets: [{{
            label: 'Cumul P&L ($)',
            data: vals,
            borderColor: '#3b82f6',
            backgroundColor: function(ctx){{
              var g = ctx.chart.ctx.createLinearGradient(0,0,0,300);
              g.addColorStop(0,'rgba(16,185,129,0.3)');
              g.addColorStop(0.5,'rgba(16,185,129,0.05)');
              g.addColorStop(1,'rgba(239,68,68,0.1)');
              return g;
            }},
            fill: 'origin',
            tension: 0.3,
            pointRadius: vals.length > 100 ? 0 : 2,
            borderWidth: 2,
          }}]
        }},
        options: {{
          responsive: true,
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            x: {{ ticks: {{ color: '#9ca3af', maxTicksLimit: 12 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
            y: {{ ticks: {{ color: '#9ca3af', callback: v => '$' + v.toFixed(0) }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
          }}
        }}
      }});
    }})();
    </script>
    """

    if has_rolling:
        rolling_chart = f"""
        <div class="card">
          <div style="font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:16px">Rolling 20-trade Win Rate</div>
          <canvas id="chartRollingWR" height="200"></canvas>
        </div>
        <script>
        (function(){{
          var ctx = document.getElementById('chartRollingWR').getContext('2d');
          new Chart(ctx, {{
            type: 'line',
            data: {{
              labels: {rolling_labels},
              datasets: [
                {{
                  label: 'Win Rate (%)',
                  data: {rolling_values},
                  borderColor: '#06b6d4',
                  backgroundColor: 'rgba(6,182,212,0.08)',
                  fill: true,
                  tension: 0.3,
                  pointRadius: {len(tm.get("rolling_values", []))} > 100 ? 0 : 2,
                  borderWidth: 2,
                }},
                {{
                  label: '50% target',
                  data: {flat50},
                  borderColor: 'rgba(255,255,255,0.2)',
                  borderDash: [5, 3],
                  pointRadius: 0,
                  borderWidth: 1,
                  fill: false,
                }}
              ]
            }},
            options: {{
              responsive: true,
              plugins: {{ legend: {{ display: false }} }},
              scales: {{
                x: {{ ticks: {{ color: '#9ca3af', maxTicksLimit: 12 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
                y: {{ min: 0, max: 100, ticks: {{ color: '#9ca3af', callback: v => v + '%' }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
              }}
            }}
          }});
        }})();
        </script>
        """
    else:
        rolling_chart = '<div class="card" style="color:var(--muted);text-align:center;padding:40px;font-size:.85rem">Rolling WR beschikbaar vanaf 20 closed trades.</div>'

    return f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">{cumul_chart}{rolling_chart}</div>'


def _build_funnel(fm: dict, pm: dict = None) -> str:
    if not fm.get("has_learning"):
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px;font-size:.85rem">SwarmLearner draait elke 20 cycles — nog geen rapport beschikbaar.</div>'

    total = fm["total"]
    passed = fm["passed_score"]
    bc = fm["build_case"]
    executed = fm["executed"]

    def pct(a, b):
        return f"{a/b*100:.1f}%" if b else "—"

    # Determine bottleneck stage
    drops = [
        ("score_threshold", total - passed if total else 0),
        ("llm_build_case", passed - bc if passed else 0),
        ("execution", bc - executed if bc else 0),
    ]
    bottleneck_stage = max(drops, key=lambda x: x[1])[0] if drops else ""

    def step_style(gate):
        if gate == bottleneck_stage:
            return "border:2px solid var(--red);position:relative"
        return "border:1px solid var(--border)"

    def bottleneck_badge(gate):
        if gate == bottleneck_stage:
            return '<span style="position:absolute;top:-10px;right:10px;background:var(--red);color:white;font-size:.65rem;padding:2px 8px;border-radius:8px;font-weight:700">BOTTLENECK</span>'
        return ""

    score_thresh = pm.get("score_threshold", "0.25") if (pm and hasattr(pm, "get")) else "0.25"
    funnel_html = f"""
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:12px;line-height:1.5">
      Onderstaande funnel toont de <strong style="color:var(--text)">laatste 2000 beslissingen</strong> (rolling window van SwarmLearner).
      "Uitgevoerd" komt uit trade_log.json en telt alle trades ooit geopend — niet beperkt tot de 2000-window.
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:8px">
      <div class="card" style="{step_style('none')};text-align:center">
        <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:6px">Geanalyseerd</div>
        <div style="font-size:1.6rem;font-weight:700">{total}</div>
        <div style="font-size:.75rem;color:var(--muted)">rolling window</div>
        <div style="font-size:.7rem;color:var(--muted);margin-top:4px">alle beslissingen in pipeline</div>
      </div>
      <div class="card" style="{step_style('score_threshold')};text-align:center">
        {bottleneck_badge('score_threshold')}
        <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:6px">Score Gate</div>
        <div style="font-size:1.6rem;font-weight:700">{passed}</div>
        <div style="font-size:.75rem;color:var(--muted)">{pct(passed, total)}</div>
        <div style="font-size:.7rem;color:var(--muted);margin-top:4px">algoritmisch filter ≥ {score_thresh}</div>
      </div>
      <div class="card" style="{step_style('llm_build_case')};text-align:center">
        {bottleneck_badge('llm_build_case')}
        <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:6px">LLM BUILD_CASE</div>
        <div style="font-size:1.6rem;font-weight:700">{bc}</div>
        <div style="font-size:.75rem;color:var(--muted)">{pct(bc, total)}</div>
        <div style="font-size:.7rem;color:var(--muted);margin-top:4px">LLM zegt: trade nu</div>
      </div>
      <div class="card" style="{step_style('execution')};text-align:center">
        {bottleneck_badge('execution')}
        <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:6px">Uitgevoerd</div>
        <div style="font-size:1.6rem;font-weight:700">{executed}</div>
        <div style="font-size:.75rem;color:var(--muted)">{pct(executed, total)}</div>
        <div style="font-size:.7rem;color:var(--muted);margin-top:4px">orders op HL geplaatst (all-time)</div>
      </div>
    </div>
    """

    # Analyst scores
    tech = fm["avg_tech"]
    fund = fm["avg_fund"]
    sent = fm["avg_sent"]
    lowest = fm["lowest_contributor"]

    def analyst_color(key, val):
        if key == lowest:
            return "var(--red)"
        return "var(--green)" if val > 0 else "var(--yellow)"

    analyst_html = f"""
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:10px">
      Gemiddelde analyst-scores over alle analyses in de 2000-window. Score +1.0 = maximaal bullish, -1.0 = maximaal bearish.
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">
      <div class="card" style="{'border:1px solid var(--red)' if lowest=='tech' else ''}">
        <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:6px">Technische Analyse</div>
        <div style="font-size:1.4rem;font-weight:700;color:{analyst_color('tech',tech)}">{tech:+.3f}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-top:6px;line-height:1.4">Prijspatronen: MACD, RSI, EMA, Bollinger, ADX. Dicht bij 0 = rangebound markt, geen actie mogelijk.</div>
        {'<div style="font-size:.7rem;color:var(--red);margin-top:6px;font-weight:600">▼ laagste bijdrage</div>' if lowest=='tech' else ''}
      </div>
      <div class="card" style="{'border:1px solid var(--red)' if lowest=='fund' else ''}">
        <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:6px">Fundamentele Analyse</div>
        <div style="font-size:1.4rem;font-weight:700;color:{analyst_color('fund',fund)}">{fund:+.3f}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-top:6px;line-height:1.4">TVL, adoptie, liquiditeit. Meet kwaliteit van het asset, niet de richting. Bij SHORT-trades is negatieve FA-bijdrage normaal gedrag.</div>
        {'<div style="font-size:.7rem;color:var(--red);margin-top:4px">▼ laagste bijdrage</div>' if lowest=='fund' else ''}
      </div>
      <div class="card" style="{'border:1px solid var(--red)' if lowest=='sent' else ''}">
        <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;margin-bottom:6px">Sentiment Analyse</div>
        <div style="font-size:1.4rem;font-weight:700;color:{analyst_color('sent',sent)}">{sent:+.3f}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-top:6px;line-height:1.4">Nieuws &amp; social media. Positief = markt is bullish gestemd. Negatief = fear/panic. Beïnvloedt 15–20% van de totaalscore.</div>
        {'<div style="font-size:.7rem;color:var(--red);margin-top:6px;font-weight:600">▼ laagste bijdrage</div>' if lowest=='sent' else ''}
      </div>
    </div>
    """

    return funnel_html + analyst_html


def _build_daily_decisions(fm: dict) -> str:
    labels = fm.get("daily_labels", [])
    if not labels:
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px;font-size:.85rem">Onvoldoende beslissingshistorie beschikbaar.</div>'

    bc = json.dumps(fm["daily_bc_counts"])
    nogo = json.dumps(fm["daily_nogo_counts"])
    pct = json.dumps(fm["daily_bc_pct"])
    lbls = json.dumps(labels)

    return f"""
    <div class="card">
      <div style="font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:16px">Beslissingen per dag (laatste 14 dagen)</div>
      <canvas id="chartDailyDecisions" height="180"></canvas>
    </div>
    <script>
    (function(){{
      var ctx = document.getElementById('chartDailyDecisions').getContext('2d');
      new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: {lbls},
          datasets: [
            {{
              label: 'BUILD_CASE',
              data: {bc},
              backgroundColor: 'rgba(59,130,246,0.7)',
              stack: 'decisions',
            }},
            {{
              label: 'NO_GO / MONITOR',
              data: {nogo},
              backgroundColor: 'rgba(75,85,99,0.4)',
              stack: 'decisions',
            }},
            {{
              label: 'BUILD_CASE %',
              data: {pct},
              type: 'line',
              borderColor: '#06b6d4',
              backgroundColor: 'transparent',
              pointRadius: 3,
              borderWidth: 2,
              yAxisID: 'yPct',
            }}
          ]
        }},
        options: {{
          responsive: true,
          plugins: {{ legend: {{ labels: {{ color: '#9ca3af', font: {{ size: 11 }} }} }} }},
          scales: {{
            x: {{ ticks: {{ color: '#9ca3af' }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
            y: {{ stacked: true, ticks: {{ color: '#9ca3af' }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
            yPct: {{ position: 'right', min: 0, max: 100, ticks: {{ color: '#06b6d4', callback: v => v + '%' }}, grid: {{ display: false }} }}
          }}
        }}
      }});
    }})();
    </script>
    """


def _build_trade_quality(tm: dict) -> str:
    if not tm.get("n"):
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px">Nog geen closed trades.</div>'

    sl = tm.get("sl_stage_stats", {})
    dirs = tm.get("direction_stats", {})

    def wr_color(wr):
        if wr >= 50:
            return "var(--green)"
        if wr >= 35:
            return "var(--yellow)"
        return "var(--red)"

    def pnl_color(pnl):
        return "var(--green)" if pnl >= 0 else "var(--red)"

    # SL stage table
    rows = ""
    stage_labels = {"0": ("SL niet bewogen", "rgba(239,68,68,0.06)"), "1": ("SL → breakeven", ""), "2+": ("SL trailing", "rgba(16,185,129,0.06)")}
    for key, (label, bg) in stage_labels.items():
        s = sl.get(key, {"n": 0, "wins": 0, "wr": 0.0, "pnl": 0.0})
        rows += f"""
        <tr style="background:{bg}">
          <td style="padding:10px 12px;font-weight:600">Stage {key}</td>
          <td style="padding:10px 12px;color:var(--muted);font-size:.8rem">{label}</td>
          <td style="padding:10px 12px;text-align:center">{s['n']}</td>
          <td style="padding:10px 12px;text-align:center;color:{wr_color(s['wr'])};font-weight:600">{s['wr']}%</td>
          <td style="padding:10px 12px;text-align:right;color:{pnl_color(s['pnl'])}">${s['pnl']:+.2f}</td>
        </tr>
        """

    sl_table = f"""
    <div class="card">
      <div style="font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">
        SL Stage Progressie
        <span style="font-size:.7rem;font-weight:400;color:var(--muted);margin-left:8px">(sl_stage≥1 historisch 3–4× hogere WR)</span>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:.85rem">
        <thead>
          <tr style="border-bottom:1px solid var(--border)">
            <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:500">Stage</th>
            <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:500"></th>
            <th style="padding:8px 12px;text-align:center;color:var(--muted);font-weight:500">N</th>
            <th style="padding:8px 12px;text-align:center;color:var(--muted);font-weight:500">WR%</th>
            <th style="padding:8px 12px;text-align:right;color:var(--muted);font-weight:500">P&L</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """

    # Direction stats
    long_s = dirs.get("LONG", {"n": 0, "wr": 0, "pnl": 0})
    short_s = dirs.get("SHORT", {"n": 0, "wr": 0, "pnl": 0})
    dir_html = f"""
    <div class="card">
      <div style="font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:16px">Long vs Short</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2);border-radius:10px;padding:16px;text-align:center">
          <div style="font-size:.75rem;color:var(--muted);margin-bottom:6px">LONG</div>
          <div style="font-size:1.8rem;font-weight:700;color:{wr_color(long_s['wr'])}">{long_s['wr']}%</div>
          <div style="font-size:.8rem;color:var(--muted);margin-top:4px">N={long_s['n']}</div>
          <div style="font-size:.8rem;color:{pnl_color(long_s['pnl'])};margin-top:2px">${long_s['pnl']:+.2f}</div>
        </div>
        <div style="background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.15);border-radius:10px;padding:16px;text-align:center">
          <div style="font-size:.75rem;color:var(--muted);margin-bottom:6px">SHORT</div>
          <div style="font-size:1.8rem;font-weight:700;color:{wr_color(short_s['wr'])}">{short_s['wr']}%</div>
          <div style="font-size:.8rem;color:var(--muted);margin-top:4px">N={short_s['n']}</div>
          <div style="font-size:.8rem;color:{pnl_color(short_s['pnl'])};margin-top:2px">${short_s['pnl']:+.2f}</div>
        </div>
      </div>
    </div>
    """

    return f'<div style="display:grid;grid-template-columns:3fr 2fr;gap:20px">{sl_table}{dir_html}</div>'


def _build_close_reasons(tm: dict) -> str:
    reasons = tm.get("close_reason_stats", [])
    if not reasons:
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px">Geen close reason data.</div>'

    labels = json.dumps([r["reason"] for r in reasons[:12]])
    counts = json.dumps([r["n"] for r in reasons[:12]])
    colors = []
    for r in reasons[:12]:
        rr = r["reason"].upper()
        if "TAKE_PROFIT" in rr or "TP" in rr:
            colors.append("rgba(16,185,129,0.7)")
        elif "STOP_LOSS" in rr or "SL" in rr:
            colors.append("rgba(239,68,68,0.7)")
        elif "TIME_EXIT" in rr:
            colors.append("rgba(245,158,11,0.7)")
        else:
            colors.append("rgba(75,85,99,0.6)")

    return f"""
    <div class="card">
      <div style="font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:16px">Close Reasons</div>
      <canvas id="chartCloseReasons" height="180"></canvas>
    </div>
    <script>
    (function(){{
      var ctx = document.getElementById('chartCloseReasons').getContext('2d');
      new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: {labels},
          datasets: [{{
            data: {counts},
            backgroundColor: {json.dumps(colors)},
            borderRadius: 4,
          }}]
        }},
        options: {{
          indexAxis: 'y',
          responsive: true,
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            x: {{ ticks: {{ color: '#9ca3af' }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
            y: {{ ticks: {{ color: '#9ca3af', font: {{ size: 11 }} }}, grid: {{ display: false }} }}
          }}
        }}
      }});
    }})();
    </script>
    """


def _build_conviction(tm: dict) -> str:
    conv = tm.get("conviction_stats", {})
    has_data = any(v["n"] > 0 for v in conv.values()) if conv else False
    if not has_data:
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px;font-size:.85rem">Onvoldoende conviction data (veld ontbreekt op trades).</div>'

    labels = json.dumps(["Low (<0.3)", "Mid (0.3–0.5)", "High (>0.5)"])
    wrs = json.dumps([conv.get("low", {}).get("wr", 0), conv.get("mid", {}).get("wr", 0), conv.get("high", {}).get("wr", 0)])
    ns = [conv.get(k, {}).get("n", 0) for k in ["low", "mid", "high"]]
    ns_str = " / ".join(f"{k}: N={n}" for k, n in zip(["Low","Mid","High"], ns))

    return f"""
    <div class="card">
      <div style="font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Conviction vs Uitkomst</div>
      <div style="font-size:.75rem;color:var(--muted);margin-bottom:12px">{ns_str}</div>
      <canvas id="chartConviction" height="160"></canvas>
    </div>
    <script>
    (function(){{
      var ctx = document.getElementById('chartConviction').getContext('2d');
      new Chart(ctx, {{
        type: 'bar',
        data: {{
          labels: {labels},
          datasets: [{{
            label: 'Win Rate (%)',
            data: {wrs},
            backgroundColor: ['rgba(239,68,68,0.6)','rgba(245,158,11,0.6)','rgba(16,185,129,0.6)'],
            borderRadius: 6,
          }}]
        }},
        options: {{
          responsive: true,
          plugins: {{ legend: {{ display: false }} }},
          scales: {{
            x: {{ ticks: {{ color: '#9ca3af' }}, grid: {{ display: false }} }},
            y: {{ min: 0, max: 100, ticks: {{ color: '#9ca3af', callback: v => v + '%' }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
          }}
        }}
      }});
    }})();
    </script>
    """


# ── Changelog ────────────────────────────────────────────────────────────────

def _compute_changelog_impact(entries: list, closed_trades: list) -> list:
    if not entries:
        return []
    sorted_entries = sorted(entries, key=lambda e: _parse_ts(e.get('timestamp', '')))
    results = []
    for i, entry in enumerate(sorted_entries):
        start_ts = _parse_ts(entry.get('timestamp', ''))
        end_ts = _parse_ts(sorted_entries[i + 1].get('timestamp', '')) if i + 1 < len(sorted_entries) else float('inf')
        # Filter on entry_time (when trade was OPENED), not exit_time.
        # A parameter change affects new trades only — measuring closed trades
        # in the window picks up trades opened before the change (misleading).
        window = [
            t for t in closed_trades
            if start_ts <= _parse_ts(t.get('entry_time') or t.get('open_time') or t.get('created_at') or 0) < end_ts
        ]
        n = len(window)
        if n > 0:
            pnls = [float(t.get('pnl') or 0) for t in window]
            wins = sum(1 for p in pnls if p > 0)
            wr = round(wins / n * 100, 1)
            total_pnl = round(sum(pnls), 2)
        else:
            wr = None
            total_pnl = None
        results.append({**entry, 'window_n': n, 'window_wr': wr, 'window_pnl': total_pnl})
    return results


def _build_changelog(entries: list) -> str:
    if not entries:
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px;font-size:.85rem">Geen wijzigingen gelogd — voeg toe via config/changelog.json.</div>'

    CAT_COLORS = {
        "param_change":    ("var(--yellow)", "rgba(245,158,11,0.12)"),
        "code_change":     ("var(--blue)",   "rgba(59,130,246,0.12)"),
        "strategy_change": ("var(--purple)", "rgba(139,92,246,0.12)"),
    }

    rows = ""
    for e in reversed(entries):  # nieuwste bovenaan
        ts    = e.get('timestamp', '')[:10]
        title = _html.escape(e.get('title', '—'))
        desc  = _html.escape(e.get('description', ''))
        cat   = e.get('category', 'code_change')
        n     = e.get('window_n', 0)
        wr    = e.get('window_wr')
        pnl   = e.get('window_pnl')

        cat_color, cat_bg = CAT_COLORS.get(cat, ("var(--muted)", "rgba(75,85,99,0.12)"))

        if wr is None:
            wr_cell = '<span style="color:var(--muted);font-size:.75rem">te vroeg</span>'
        elif wr >= 40:
            wr_cell = f'<span style="color:var(--green);font-weight:700">{wr}%</span>'
        elif wr >= 30:
            wr_cell = f'<span style="color:var(--yellow);font-weight:700">{wr}%</span>'
        else:
            wr_cell = f'<span style="color:var(--red);font-weight:700">{wr}%</span>'

        if pnl is None:
            pnl_cell = '<span style="color:var(--muted)">—</span>'
        elif pnl >= 0:
            pnl_cell = f'<span style="color:var(--green)">${pnl:+.2f}</span>'
        else:
            pnl_cell = f'<span style="color:var(--red)">${pnl:+.2f}</span>'

        n_cell = str(n) if n > 0 else '<span style="color:var(--muted)">0</span>'

        rows += f"""
        <tr style="border-bottom:1px solid var(--border)">
          <td style="padding:10px 12px;color:var(--muted);font-size:.8rem;white-space:nowrap">{ts}</td>
          <td style="padding:10px 12px">
            <div style="font-weight:600;font-size:.85rem;margin-bottom:3px">{title}</div>
            <div style="font-size:.75rem;color:var(--muted);line-height:1.4">{desc}</div>
          </td>
          <td style="padding:10px 12px;text-align:center">
            <span style="background:{cat_bg};color:{cat_color};padding:2px 8px;border-radius:6px;font-size:.7rem;white-space:nowrap">{cat.replace('_', ' ')}</span>
          </td>
          <td style="padding:10px 12px;text-align:center;font-size:.85rem">{n_cell}</td>
          <td style="padding:10px 12px;text-align:center">{wr_cell}</td>
          <td style="padding:10px 12px;text-align:right">{pnl_cell}</td>
        </tr>
        """

    return f"""
    <div class="card">
      <div style="font-size:.75rem;color:var(--muted);margin-bottom:14px;line-height:1.5">
        WR% en P&L zijn berekend over trades die <em>geopend</em> zijn ná de wijziging (tot aan de volgende wijziging).
        Zo meet je het echte effect — niet de staart van trades die al liepen. Wijzigingen toevoegen via <code style="color:var(--blue)">config/changelog.json</code>.
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:.85rem">
        <thead>
          <tr style="border-bottom:2px solid var(--border)">
            <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:500;white-space:nowrap">Datum</th>
            <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:500">Wijziging</th>
            <th style="padding:8px 12px;text-align:center;color:var(--muted);font-weight:500">Type</th>
            <th style="padding:8px 12px;text-align:center;color:var(--muted);font-weight:500">Trades</th>
            <th style="padding:8px 12px;text-align:center;color:var(--muted);font-weight:500">WR%</th>
            <th style="padding:8px 12px;text-align:right;color:var(--muted);font-weight:500">P&L</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


# ── Page assembly ─────────────────────────────────────────────────────────────

_PERF_CSS = """
:root{--bg:#0a0e17;--card:rgba(17,24,39,0.8);--border:rgba(75,85,99,0.4);--text:#f9fafb;--muted:#9ca3af;--green:#10b981;--red:#ef4444;--yellow:#f59e0b;--blue:#3b82f6;--purple:#8b5cf6;--cyan:#06b6d4}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;background-image:radial-gradient(ellipse at 20% 0%,rgba(59,130,246,0.15) 0%,transparent 50%),radial-gradient(ellipse at 80% 100%,rgba(139,92,246,0.1) 0%,transparent 50%)}
.container{max-width:1400px;margin:0 auto;padding:24px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--border)}
.logo{display:flex;align-items:center;gap:12px}
.logo-icon{width:44px;height:44px;background:linear-gradient(135deg,var(--blue),var(--purple));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px}
h1{font-size:1.5rem;font-weight:700;background:linear-gradient(135deg,#fff,#9ca3af);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.live{display:flex;align-items:center;gap:8px;font-size:.875rem;color:var(--muted)}
.pulse-dot{width:10px;height:10px;background:var(--green);border-radius:50%;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.7;transform:scale(1.1)}}
.nav-back{font-size:.8rem;color:var(--blue);text-decoration:none;padding:6px 12px;border:1px solid rgba(59,130,246,0.3);border-radius:6px;transition:background .2s}
.nav-back:hover{background:rgba(59,130,246,0.1)}
.section{margin-bottom:32px}
.section-header{display:flex;align-items:center;gap:10px;margin-bottom:16px}
.section-title{font-size:.9rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.section-line{flex:1;height:1px;background:var(--border)}
.card{background:var(--card);backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:14px;padding:20px;position:relative}
footer{text-align:center;padding:24px;color:var(--muted);font-size:.8rem;border-top:1px solid var(--border);margin-top:32px}
"""


def build_performance_html() -> str:
    # Load data
    trades_raw = _load_json("trade_log.json", [])
    decisions = _load_json("decision_history.json", [])
    if not isinstance(decisions, list):
        decisions = []
    learning = _load_json("learning_report.json", {})
    auto_params = _load_json("config/auto_params.json", {})
    changelog = _load_json("config/changelog.json", [])

    # Compute
    closed = _collect_closed_trades(trades_raw)
    tm = _compute_trade_metrics(closed)
    fm = _compute_funnel_metrics(learning, decisions)
    pm = _compute_param_history(auto_params)

    # Build sections
    advice_items = _generate_advice(tm, fm, pm)
    advice_html = _render_advice(advice_items)
    header_html = _build_header(tm, pm)
    timeseries_html = _build_timeseries(tm)
    funnel_html = _build_funnel(fm, pm)
    daily_html = _build_daily_decisions(fm)
    quality_html = _build_trade_quality(tm)
    reasons_html = _build_close_reasons(tm)
    conviction_html = _build_conviction(tm)
    changelog_impact = _compute_changelog_impact(changelog, closed)
    changelog_html = _build_changelog(changelog_impact)

    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>Performance Report — Agent Trader</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>{_PERF_CSS}</style>
</head>
<body>
<div class="container">

<header>
  <div class="logo">
    <div class="logo-icon">📊</div>
    <div>
      <h1>Performance Report</h1>
      <div style="font-size:.75rem;color:var(--muted)">Agent Trader Swarm</div>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:16px">
    <div class="live"><div class="pulse-dot"></div>{ts}</div>
    <a href="/" class="nav-back">← Dashboard</a>
    <a href="/focus" class="nav-back">Focus →</a>
  </div>
</header>

{header_html}

<div class="section">
  <div class="section-header">
    <span class="section-title">Adviezen &amp; Acties</span>
    <div class="section-line"></div>
  </div>
  {advice_html}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">P&L &amp; Win Rate over tijd</span>
    <div class="section-line"></div>
  </div>
  {timeseries_html}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Pipeline Funnel — huidige bottleneck</span>
    <div class="section-line"></div>
  </div>
  {funnel_html}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Beslissingen over tijd</span>
    <div class="section-line"></div>
  </div>
  {daily_html}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Trade kwaliteit</span>
    <div class="section-line"></div>
  </div>
  {quality_html}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Close Reasons &amp; Conviction</span>
    <div class="section-line"></div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
    {reasons_html}
    {conviction_html}
  </div>
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Wijzigingslogboek &amp; Impact</span>
    <div class="section-line"></div>
  </div>
  {changelog_html}
</div>

<footer>
  Auto-refresh elke 120s &nbsp;|&nbsp; Data uit trade_log.json · decision_history.json · learning_report.json · config/changelog.json
  &nbsp;|&nbsp; <a href="/" style="color:var(--blue)">Dashboard</a>
  &nbsp;|&nbsp; <a href="/focus" style="color:var(--blue)">Focus</a>
</footer>

</div>
</body>
</html>"""
