"""
Treasury dashboard — served at /treasury.

Shows:
- HL capital utilization (idle vs deployed in trades)
- Live yield opportunities on Arbitrum (Aave, Morpho, Compound)
- Pending proposals for human review
- Proposal history (approved / rejected)
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime


_CSS = """
:root{--bg:#0a0e17;--card:rgba(17,24,39,0.8);--border:rgba(75,85,99,0.4);--text:#f9fafb;--muted:#9ca3af;--green:#10b981;--red:#ef4444;--yellow:#f59e0b;--blue:#3b82f6;--purple:#8b5cf6;--cyan:#06b6d4}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;background-image:radial-gradient(ellipse at 20% 0%,rgba(59,130,246,0.15) 0%,transparent 50%),radial-gradient(ellipse at 80% 100%,rgba(139,92,246,0.1) 0%,transparent 50%)}
.container{max-width:1400px;margin:0 auto;padding:24px}
header{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:12px}
.header-right{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.logo{display:flex;align-items:center;gap:12px}
.logo-icon{width:44px;height:44px;background:linear-gradient(135deg,var(--green),var(--cyan));border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0}
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
.hl-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:20px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.table-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.proposal-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
@media(max-width:900px){
  .portfolio-grid{grid-template-columns:repeat(2,1fr)}
  .hl-grid{grid-template-columns:repeat(2,1fr)}
  .two-col{grid-template-columns:1fr}
  .container{padding:16px}
  h1{font-size:1.25rem}
}
@media(max-width:500px){
  .portfolio-grid{grid-template-columns:1fr}
  .hl-grid{grid-template-columns:1fr}
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
        return f"{float(v):.1f}%"
    except Exception:
        return "—"


def _apy_color(apy: float) -> str:
    if apy >= 8:
        return "var(--green)"
    if apy >= 5:
        return "var(--yellow)"
    return "var(--muted)"


# ── Section builders ──────────────────────────────────────────────────────────

_PROTOCOL_META: dict[str, tuple[str, str, str]] = {
    "aave-v3-arbitrum-usdc":      ("Aave v3",       "aUSDCn · Arbitrum",        "var(--green)"),
    "morpho-bbqusdc-arbitrum":    ("Morpho BBQUSDC","Gauntlet USDC · Arbitrum", "var(--purple)"),
    "morpho-gtusdcc-arbitrum":    ("Morpho GTUSDCC","Gauntlet USDC · Arbitrum", "var(--purple)"),
    "gains-network-arbitrum-usdc":("Gains Network", "gUSDC · Arbitrum",         "var(--cyan)"),
    "compound-v3-arbitrum-usdc":  ("Compound v3",   "cUSDCv3 · Arbitrum",       "var(--blue)"),
}


def _build_portfolio_overview(state: dict) -> str:
    hl             = state.get("hl_snapshot", {})
    hl_balance     = hl.get("balance", 0)
    yield_balances = state.get("yield_balances") or {}
    total_yield    = state.get("total_yield") or sum(yield_balances.values())
    wallet_usdc    = state.get("treasury_wallet_usdc", 0)
    total          = state.get("total_portfolio", 0) or round(hl_balance + total_yield + wallet_usdc, 2)
    alloc          = state.get("allocation", {})

    target_trade_pct = alloc.get("effective_trade_pct", 30)
    target_trade_usd = alloc.get("target_trade_usd", 0)
    alloc_reason     = alloc.get("reason", "")
    current_hl_pct   = round(hl_balance / total * 100, 1) if total > 0 else 0
    current_yield_pct = round(total_yield / total * 100, 1) if total > 0 else 0
    current_wallet_pct = round(wallet_usdc / total * 100, 1) if total > 0 else 0

    # ── Yield card: dynamic per active protocol ───────────────────────────────
    active = {k: v for k, v in yield_balances.items() if v > 1.0}
    if not active:
        yield_card_inner = f"""
          <div style="font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Yield Deployed</div>
          <div style="font-size:1.7rem;font-weight:700;color:var(--green)">$0.00</div>
          <div style="font-size:.72rem;color:var(--muted);margin-top:4px">geen actief protocol</div>"""
    elif len(active) == 1:
        pid, bal = next(iter(active.items()))
        lbl, sub, col = _PROTOCOL_META.get(pid, (pid[:14], "Arbitrum", "var(--green)"))
        yield_card_inner = f"""
          <div style="font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">{lbl}</div>
          <div style="font-size:1.7rem;font-weight:700;color:{col}">{_fmt_usd(bal)}</div>
          <div style="font-size:.72rem;color:var(--muted);margin-top:4px">{sub}</div>"""
    else:
        breakdown = "".join(
            f'<div style="font-size:.68rem;color:var(--muted);margin-top:3px">'
            f'{_PROTOCOL_META.get(k, (k[:14],"",""))[0]}: {_fmt_usd(v)}</div>'
            for k, v in active.items()
        )
        yield_card_inner = f"""
          <div style="font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Yield Deployed</div>
          <div style="font-size:1.7rem;font-weight:700;color:var(--green)">{_fmt_usd(total_yield)}</div>
          {breakdown}"""

    # ── Allocation bar ─────────────────────────────────────────────────────────
    target_marker = (
        f'<div style="position:absolute;left:{min(target_trade_pct,98):.0f}%;top:0;bottom:0;'
        f'width:2px;background:var(--text);opacity:0.7" title="HL doel {target_trade_pct:.0f}%"></div>'
    )
    alloc_bar = f"""
    <div class="card" style="margin-top:16px;padding:16px">
      <div style="font-size:.8rem;color:var(--muted);margin-bottom:10px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:4px">
        <span>Portfolio allocatie (HL vs Yield)</span>
        <span style="font-size:.7rem;color:var(--muted)">{alloc_reason}</span>
      </div>
      <div style="position:relative;background:rgba(75,85,99,0.3);border-radius:8px;height:24px;overflow:hidden;display:flex">
        <div style="width:{current_hl_pct:.1f}%;background:var(--blue);display:flex;align-items:center;justify-content:center;font-size:.65rem;color:#fff;font-weight:600;white-space:nowrap;overflow:hidden">
          {current_hl_pct:.0f}% HL
        </div>
        <div style="width:{current_yield_pct:.1f}%;background:var(--green);opacity:0.85;display:flex;align-items:center;justify-content:center;font-size:.65rem;color:#fff;font-weight:600;white-space:nowrap;overflow:hidden">
          {current_yield_pct:.0f}% Yield
        </div>
        <div style="width:{current_wallet_pct:.1f}%;background:var(--yellow);opacity:0.75;display:flex;align-items:center;justify-content:center;font-size:.65rem;color:#000;font-weight:600;white-space:nowrap;overflow:hidden">
          {current_wallet_pct:.0f}%
        </div>
        {target_marker}
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:12px;font-size:.72rem;color:var(--muted);margin-top:8px">
        <span>🔵 HL: {current_hl_pct:.0f}%</span>
        <span>🟢 Yield: {current_yield_pct:.0f}%</span>
        <span style="color:var(--yellow)">🟡 Wallet: {current_wallet_pct:.0f}%</span>
        <span style="margin-left:auto">▏ Doel HL: {target_trade_pct:.0f}% (${target_trade_usd:.0f})</span>
      </div>
    </div>
    """

    return f"""
    <div class="portfolio-grid">
      <div class="card" style="text-align:center">
        <div style="font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">HL Balance</div>
        <div style="font-size:1.7rem;font-weight:700;color:var(--blue)">{_fmt_usd(hl_balance)}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-top:4px">trading margin</div>
      </div>
      <div class="card" style="text-align:center">
        {yield_card_inner}
      </div>
      <div class="card" style="text-align:center">
        <div style="font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Treasury Wallet</div>
        <div style="font-size:1.7rem;font-weight:700;color:var(--yellow)">{_fmt_usd(wallet_usdc)}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-top:4px">Arbitrum USDC</div>
      </div>
      <div class="card" style="text-align:center;border-color:var(--cyan)">
        <div style="font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">Totaal Portfolio</div>
        <div style="font-size:1.7rem;font-weight:700;color:var(--cyan)">{_fmt_usd(total)}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-top:4px">alle locaties</div>
      </div>
    </div>
    {alloc_bar}
    """


def _build_hl_snapshot(hl: dict) -> str:
    if hl.get("error"):
        return f'<div class="card" style="color:var(--red)">HL snapshot mislukt: {_html.escape(hl["error"])}</div>'

    balance  = hl.get("balance", 0)
    free     = hl.get("free_margin", 0)
    deployed = hl.get("deployed_margin", 0)
    idle_pct = hl.get("idle_pct", 0)

    deployed_pct = 100 - idle_pct
    bar_color = "var(--green)" if idle_pct < 40 else ("var(--yellow)" if idle_pct < 65 else "var(--red)")

    idle_label = (
        "Optimaal — voldoende margin voor trades" if idle_pct < 40
        else "Matig idle — overweeg yield deployment" if idle_pct < 65
        else "Veel idle kapitaal — treasury voorstel actief"
    )

    return f"""
    <div class="hl-grid">
      <div class="card" style="text-align:center">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Totaal saldo HL</div>
        <div style="font-size:2rem;font-weight:700">{_fmt_usd(balance)}</div>
        <div style="font-size:.75rem;color:var(--muted);margin-top:4px">Hyperliquid perps</div>
      </div>
      <div class="card" style="text-align:center">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">In open trades</div>
        <div style="font-size:2rem;font-weight:700;color:var(--blue)">{_fmt_usd(deployed)}</div>
        <div style="font-size:.75rem;color:var(--muted);margin-top:4px">{_fmt_pct(deployed_pct)} van saldo</div>
      </div>
      <div class="card" style="text-align:center;border:1px solid {bar_color}">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">Idle (vrije margin)</div>
        <div style="font-size:2rem;font-weight:700;color:{bar_color}">{_fmt_usd(free)}</div>
        <div style="font-size:.75rem;color:{bar_color};margin-top:4px">{_fmt_pct(idle_pct)} — {idle_label}</div>
      </div>
    </div>
    <div class="card" style="padding:16px">
      <div style="font-size:.8rem;color:var(--muted);margin-bottom:10px">Kapitaalbenutting HL</div>
      <div style="background:rgba(75,85,99,0.3);border-radius:8px;height:20px;overflow:hidden;display:flex">
        <div style="width:{deployed_pct:.0f}%;background:var(--blue);transition:width .5s"></div>
        <div style="width:{idle_pct:.0f}%;background:{bar_color};opacity:0.5;transition:width .5s"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:.75rem;color:var(--muted);margin-top:6px">
        <span>🔵 In trades: {deployed_pct:.0f}%</span>
        <span style="color:{bar_color}">⬜ Idle: {idle_pct:.0f}%</span>
      </div>
    </div>
    """


_TIER_META = {
    "stable":   ("🟢", "Stabiel",         "var(--green)",  "rgba(16,185,129,0.10)", "Smart contract risico. Geen prijsblootstelling."),
    "medium":   ("🟡", "Delta-neutraal",  "var(--yellow)", "rgba(245,158,11,0.10)", "Funding rate mechanisme. Hoger rendement, iets complexer."),
    "exposure": ("🔵", "Prijs-exposure",  "var(--blue)",   "rgba(59,130,246,0.10)", "Rendement + prijsbeweging van het onderliggende asset."),
}


def _build_opportunities(opps: list) -> str:
    if not opps:
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px;font-size:.85rem">DeFiLlama data niet beschikbaar — check network.</div>'

    # Group by risk tier
    tiers = {"stable": [], "medium": [], "exposure": []}
    for o in opps:
        tiers.setdefault(o.get("risk_tier", "stable"), []).append(o)

    sections = ""
    for tier_key in ("stable", "medium", "exposure"):
        tier_opps = tiers.get(tier_key, [])
        if not tier_opps:
            continue
        icon, tier_label, color, bg, desc = _TIER_META[tier_key]
        rows = ""
        for i, o in enumerate(tier_opps):
            apy = o.get("apy", 0)
            apy_color = _apy_color(apy)
            tvl = o.get("tvl_usd", 0)
            tvl_str = f"${tvl/1e9:.1f}B" if tvl >= 1e9 else f"${tvl/1e6:.0f}M" if tvl >= 1e6 else "—"
            reward_str = f'<div style="font-size:.68rem;color:var(--cyan)">+{o["apy_reward"]:.1f}% rewards</div>' if o.get("apy_reward", 0) > 0.1 else ""
            top_badge = '<span style="background:rgba(16,185,129,0.15);color:var(--green);font-size:.62rem;padding:1px 6px;border-radius:4px;margin-left:6px">BEST</span>' if i == 0 else ""

            rows += f"""
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:10px 14px;font-weight:600;font-size:.85rem">{_html.escape(o['label'])}{top_badge}</td>
              <td style="padding:10px 14px;text-align:center">
                <span style="font-size:1.05rem;font-weight:700;color:{apy_color}">{apy:.2f}%</span>
                {reward_str}
              </td>
              <td style="padding:10px 14px;text-align:center;color:var(--muted);font-size:.82rem">{tvl_str}</td>
              <td style="padding:10px 14px;text-align:center;color:var(--muted);font-size:.72rem">{o.get("chain","—")}</td>
            </tr>
            """

        sections += f"""
        <div class="card" style="margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">
            <span style="font-size:1.1rem">{icon}</span>
            <div>
              <span style="font-weight:700;color:{color}">{tier_label}</span>
              <span style="font-size:.75rem;color:var(--muted);margin-left:10px">{desc}</span>
            </div>
          </div>
          <div class="table-scroll">
          <table style="width:100%;border-collapse:collapse;min-width:320px">
            <thead>
              <tr style="border-bottom:1px solid var(--border)">
                <th style="padding:6px 14px;text-align:left;color:var(--muted);font-weight:500;font-size:.78rem">Protocol</th>
                <th style="padding:6px 14px;text-align:center;color:var(--muted);font-weight:500;font-size:.78rem">APY</th>
                <th style="padding:6px 14px;text-align:center;color:var(--muted);font-weight:500;font-size:.78rem">TVL</th>
                <th style="padding:6px 14px;text-align:center;color:var(--muted);font-weight:500;font-size:.78rem">Chain</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
          </div>
        </div>
        """

    return f"""
    <div style="font-size:.75rem;color:var(--muted);margin-bottom:14px;line-height:1.5">
      Live data via DeFiLlama — hoofdpool per protocol (gefilterd op minimale TVL). Arbitrum = HL native bridge route. Ethereum = aparte bridge stap nodig.
    </div>
    {sections}
    """


_EXEC_STATUS = {
    "APPROVED":                ("🟡", "var(--yellow)", "Goedgekeurd — wordt gestart…"),
    "WITHDRAWING":             ("🔄", "var(--blue)",   "HL → Arbitrum bridge in uitvoering (~15 min)…"),
    "NEEDS_MANUAL_WITHDRAWAL": ("⚠️", "var(--yellow)", "Handmatige HL withdrawal nodig — zie Telegram"),
    "BRIDGED":                 ("🔵", "var(--cyan)",   "USDC gearriveerd op Arbitrum — Aave deposit loopt…"),
    "REBALANCING":             ("🔄", "var(--purple)", "Aave withdrawal in uitvoering…"),
    "BRIDGE_BACK_NEEDED":      ("⚠️", "var(--yellow)", "USDC op Arbitrum — bridge handmatig naar HL (zie Telegram)"),
    "DEPLOYED":                ("✅", "var(--green)",  "Gedeployed in yield protocol"),
    "FAILED":                  ("❌", "var(--red)",    "Mislukt — zie logs / Telegram"),
}


def _build_proposals(proposals: list) -> str:
    pending    = [p for p in proposals if p.get("status") == "PENDING"]
    in_flight  = [p for p in proposals if p.get("status") in _EXEC_STATUS and p.get("status") not in ("DEPLOYED", "FAILED", "BRIDGE_BACK_NEEDED")]
    waiting    = [p for p in proposals if p.get("status") == "BRIDGE_BACK_NEEDED"]
    history    = [p for p in proposals if p.get("status") in ("DEPLOYED", "FAILED", "REJECTED")]

    if not proposals:
        return '<div class="card" style="color:var(--muted);text-align:center;padding:40px;font-size:.85rem">Geen voorstellen — TreasuryAgent draait elk uur. Verschijnt wanneer idle &gt; 60%.</div>'

    sections = ""

    # ── Pending proposals → Goedkeuren button ────────────────────────────────
    for p in pending:
        steps_html = "".join(
            f'<div style="font-size:.78rem;color:var(--muted);padding:3px 0;border-bottom:1px solid rgba(75,85,99,0.2)">{_html.escape(s)}</div>'
            for s in p.get("steps", [])
        )
        monthly = p.get("projected_monthly", 0)
        yearly  = p.get("projected_yearly", 0)
        pid     = _html.escape(p.get("id", ""))

        sections += f"""
        <div style="background:rgba(245,158,11,0.06);border:1px solid rgba(245,158,11,0.35);border-radius:14px;padding:20px;margin-bottom:16px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
            <div>
              <div style="font-size:.7rem;color:var(--yellow);font-weight:600;letter-spacing:1px;margin-bottom:4px">⏳ WACHT OP GOEDKEURING — {pid}</div>
              <div style="font-size:1rem;font-weight:700">{_html.escape(p.get('title',''))}</div>
            </div>
            <div style="text-align:right">
              <div style="font-size:.75rem;color:var(--muted)">Verwacht rendement</div>
              <div style="font-size:1.2rem;font-weight:700;color:var(--green)">${monthly:.2f}/mnd</div>
              <div style="font-size:.75rem;color:var(--muted)">${yearly:.2f}/jaar</div>
            </div>
          </div>
          <div style="font-size:.82rem;color:var(--text);line-height:1.6;margin-bottom:14px">{_html.escape(p.get('rationale',''))}</div>
          <div style="background:rgba(0,0,0,0.2);border-radius:8px;padding:12px;margin-bottom:14px">
            <div style="font-size:.75rem;color:var(--muted);font-weight:600;margin-bottom:6px">WAT ER GEBEURT NA GOEDKEURING:</div>
            {steps_html}
          </div>
          <div class="proposal-actions">
            <button onclick="approveTreasury('{pid}')" id="btn-{pid}"
              style="background:linear-gradient(135deg,var(--green),var(--cyan));color:#fff;border:none;border-radius:8px;padding:10px 24px;font-size:.9rem;font-weight:700;cursor:pointer;transition:opacity .2s;white-space:nowrap">
              ✅ Goedkeuren — automatisch uitvoeren
            </button>
            <span style="font-size:.75rem;color:var(--muted)">Deposit wordt automatisch uitgevoerd na klik.</span>
          </div>
        </div>
        """

    # ── In-flight proposals → status display ─────────────────────────────────
    for p in in_flight:
        status = p.get("status", "")
        icon, color, label = _EXEC_STATUS.get(status, ("⏳", "var(--muted)", status))
        dest = p.get("withdrawal_destination", "")
        extra = ""
        if status == "NEEDS_MANUAL_WITHDRAWAL" and dest:
            extra = f'<div style="font-size:.78rem;color:var(--yellow);margin-top:8px;padding:8px;background:rgba(245,158,11,0.08);border-radius:6px">Withdrawal bestemming (Arbitrum): <code>{dest}</code></div>'
        if status == "BRIDGED":
            bal = p.get("arb_usdc_balance", 0)
            extra = f'<div style="font-size:.78rem;color:var(--cyan);margin-top:8px">${bal:.2f} USDC gedetecteerd op Arbitrum — Aave deposit loopt…</div>'

        sections += f"""
        <div style="background:rgba(59,130,246,0.05);border:1px solid rgba(59,130,246,0.25);border-radius:14px;padding:20px;margin-bottom:16px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <div style="font-size:.7rem;color:{color};font-weight:600;letter-spacing:1px;margin-bottom:4px">{icon} {status} — {p.get('id','')}</div>
              <div style="font-size:1rem;font-weight:700">{_html.escape(p.get('title',''))}</div>
              <div style="font-size:.82rem;color:var(--muted);margin-top:4px">{label}</div>
              {extra}
            </div>
            <div style="text-align:right">
              <div style="font-size:.75rem;color:var(--muted)">APY</div>
              <div style="font-size:1.2rem;font-weight:700;color:var(--green)">{p.get('apy',0):.1f}%</div>
            </div>
          </div>
        </div>
        """

    # ── BRIDGE_BACK_NEEDED: manual deposit to HL required ────────────────────
    for p in waiting:
        amount = p.get("amount_usd", 0)
        sections += f"""
        <div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.4);border-radius:14px;padding:20px;margin-bottom:16px">
          <div style="font-size:.7rem;color:var(--yellow);font-weight:600;letter-spacing:1px;margin-bottom:6px">⚠️ HANDMATIGE STAP NODIG — {p.get('id','')}</div>
          <div style="font-size:1rem;font-weight:700;margin-bottom:8px">{_html.escape(p.get('title',''))}</div>
          <div style="font-size:.85rem;color:var(--text);margin-bottom:12px">
            ${amount:.0f} USDC staat klaar op het treasury wallet op Arbitrum.<br>
            Deposit dit naar Hyperliquid via de HL web app om het handelsvermogen te herstellen.
          </div>
          <div style="background:rgba(0,0,0,0.2);border-radius:8px;padding:12px;font-size:.82rem;color:var(--muted)">
            1. Ga naar <strong style="color:var(--text)">app.hyperliquid.xyz</strong><br>
            2. Transfer → Deposit from Arbitrum<br>
            3. Bedrag: <strong style="color:var(--yellow)">${amount:.0f} USDC</strong>
          </div>
        </div>
        """

    # ── History ───────────────────────────────────────────────────────────────
    if history:
        hist_rows = ""
        for p in sorted(history, key=lambda x: x.get("created_at", ""), reverse=True)[:15]:
            status = p.get("status", "")
            color  = {"DEPLOYED": "var(--green)", "FAILED": "var(--red)", "REJECTED": "var(--muted)"}.get(status, "var(--muted)")
            tx_cell = f'<code style="font-size:.65rem">{p.get("aave_tx","")[:16]}…</code>' if p.get("aave_tx") else "—"
            hist_rows += f"""
            <tr style="border-bottom:1px solid var(--border)">
              <td style="padding:8px 12px;color:var(--muted);font-size:.78rem">{p.get('created_at','')[:10]}</td>
              <td style="padding:8px 12px;font-size:.82rem">{_html.escape(p.get('title',''))}</td>
              <td style="padding:8px 12px;text-align:center;color:{color};font-weight:600;font-size:.78rem">{status}</td>
              <td style="padding:8px 12px;text-align:center;font-size:.78rem;color:var(--muted)">{tx_cell}</td>
              <td style="padding:8px 12px;text-align:right;color:var(--green);font-size:.82rem">${p.get('projected_monthly',0):.2f}/mnd</td>
            </tr>
            """
        sections += f"""
        <div class="card">
          <div style="font-size:.85rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">Geschiedenis</div>
          <div class="table-scroll">
          <table style="width:100%;border-collapse:collapse;font-size:.85rem;min-width:400px">
            <thead><tr style="border-bottom:2px solid var(--border)">
              <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:500">Datum</th>
              <th style="padding:8px 12px;text-align:left;color:var(--muted);font-weight:500">Voorstel</th>
              <th style="padding:8px 12px;text-align:center;color:var(--muted);font-weight:500">Status</th>
              <th style="padding:8px 12px;text-align:center;color:var(--muted);font-weight:500">TX</th>
              <th style="padding:8px 12px;text-align:right;color:var(--muted);font-weight:500">Yield</th>
            </tr></thead>
            <tbody>{hist_rows}</tbody>
          </table>
          </div>
        </div>
        """

    return sections


def _build_pnl_section(state: dict) -> str:
    import json as _json
    from collections import defaultdict
    from datetime import datetime as _dt, timedelta as _td

    # ── Trading P&L from trade_log ────────────────────────────────────────────
    try:
        with open("trade_log.json") as f:
            raw = _json.load(f)
        trades = list(raw.values()) if isinstance(raw, dict) else raw
        closed = [
            t for t in trades
            if t.get("status") == "CLOSED"
            and t.get("pnl") is not None
            and not str(t.get("id", "")).startswith("RECOVERED_")
            and not t.get("harvest")
        ]
    except Exception:
        closed = []

    trade_by_day: dict[str, float] = defaultdict(float)
    fees_by_day:  dict[str, float] = defaultdict(float)
    for t in closed:
        et = t.get("exit_time", "")
        if isinstance(et, (int, float)):
            day = _dt.utcfromtimestamp(et).strftime("%Y-%m-%d")
        else:
            day = str(et)[:10]
        if len(day) == 10:
            trade_by_day[day] += float(t.get("pnl", 0))
            fees_by_day[day]  += float(t.get("fees") or 0)

    # ── Costs from cost_log ───────────────────────────────────────────────────
    try:
        with open("cost_log.json") as f:
            cl = _json.load(f)
        cost_hist = cl.get("history", cl)
    except Exception:
        cost_hist = {}

    # ── Estimated daily yield (current balance × APY / 365) ──────────────────
    yield_balances = state.get("yield_balances") or {}
    opportunities  = state.get("opportunities") or []
    apy_by_id = {
        (o.get("protocol_config") or {}).get("id", ""): o.get("apy", 0.0)
        for o in opportunities if o.get("protocol_config")
    }
    daily_yield_est = round(sum(
        bal * apy_by_id.get(pid, 0.0) / 100 / 365
        for pid, bal in yield_balances.items() if bal > 1.0
    ), 4)

    # ── Build 90-day dataset ──────────────────────────────────────────────────
    today = _dt.utcnow().date()
    days_data = []
    for i in range(89, -1, -1):
        d  = today - _td(days=i)
        ds = d.strftime("%Y-%m-%d")
        ce = cost_hist.get(ds, {})
        days_data.append({
            "date":     ds,
            "trading":  round(trade_by_day.get(ds, 0.0), 2),
            "yield":    daily_yield_est,
            "costs":    round(float(ce.get("total_cost_usd", 0)), 2),
            "has_cost": ds in cost_hist,
        })

    # Yield data note
    protocol_notes = ", ".join(
        f"{_PROTOCOL_META.get(pid, (pid[:12],'',''))[0]} ${bal:.0f} @ {apy_by_id.get(pid,0):.1f}%"
        for pid, bal in yield_balances.items() if bal > 1.0
    ) or "geen deployment"

    data_json       = _json.dumps(days_data)
    total_portfolio = float(state.get("total_portfolio") or 1)

    return f"""
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px">
    <div>
      <div style="font-size:.9rem;font-weight:600">P&amp;L overzicht</div>
      <div style="font-size:.7rem;color:var(--muted);margin-top:2px">Yield geschat: {protocol_notes}</div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button onclick="setPnlPeriod('7d')"  id="pnl-btn-7d"  class="pnl-period-btn">7 d</button>
      <button onclick="setPnlPeriod('30d')" id="pnl-btn-30d" class="pnl-period-btn pnl-active">30 d</button>
      <button onclick="setPnlPeriod('90d')" id="pnl-btn-90d" class="pnl-period-btn">90 d</button>
      <div style="width:1px;background:var(--border);margin:0 2px"></div>
      <button onclick="togglePnlMode()" id="pnl-btn-mode" class="pnl-period-btn">$ bedrag</button>
    </div>
  </div>
  <div id="pnl-summary" class="portfolio-grid" style="margin-bottom:16px"></div>
  <div style="display:flex;gap:12px;font-size:.68rem;color:var(--muted);margin-bottom:8px;flex-wrap:wrap">
    <span><span style="display:inline-block;width:10px;height:10px;background:var(--green);border-radius:2px;margin-right:4px;vertical-align:middle"></span>Trading winst</span>
    <span><span style="display:inline-block;width:10px;height:10px;background:var(--red);border-radius:2px;margin-right:4px;vertical-align:middle"></span>Trading verlies</span>
    <span><span style="display:inline-block;width:10px;height:10px;background:var(--cyan);opacity:.7;border-radius:2px;margin-right:4px;vertical-align:middle"></span>Yield (est.)</span>
    <span><span style="display:inline-block;width:10px;height:10px;background:var(--red);opacity:.4;border-radius:2px;margin-right:4px;vertical-align:middle"></span>Kosten</span>
  </div>
  <div id="pnl-chart" style="overflow-y:auto;max-height:440px"></div>
</div>
<style>
.pnl-period-btn{{background:rgba(75,85,99,0.3);color:var(--muted);border:1px solid var(--border);border-radius:6px;padding:5px 14px;font-size:.78rem;cursor:pointer;transition:all .2s;white-space:nowrap}}
.pnl-active{{background:rgba(59,130,246,0.25);color:var(--blue);border-color:rgba(59,130,246,0.5)}}
</style>
<script>
(function(){{
const DAYS = {data_json};
const TOTAL = {total_portfolio};

let curPeriod = '30d';
let curMode   = '$';

function grp(days) {{
  const m={{}};
  days.forEach(d=>{{
    const dt=new Date(d.date), wd=dt.getDay();
    const mon=new Date(dt); mon.setDate(dt.getDate()-((wd+6)%7));
    const wk=mon.toISOString().slice(0,10);
    if(!m[wk]) m[wk]={{date:wk.slice(5),trading:0,yield:0,costs:0,has_cost:false}};
    m[wk].trading+=d.trading; m[wk].yield+=d.yield;
    m[wk].costs+=d.costs; if(d.has_cost) m[wk].has_cost=true;
  }});
  return Object.values(m).map(r=>({{...r,trading:Math.round(r.trading*100)/100,yield:Math.round(r.yield*100)/100,costs:Math.round(r.costs*100)/100}}));
}}

function fv(v) {{
  if (curMode==='%') {{
    const p = TOTAL>0 ? v/TOTAL*100 : 0;
    return (p>=0?'+':'')+p.toFixed(3)+'%';
  }}
  return (v>=0?'+':'-')+'$'+Math.abs(v).toFixed(2);
}}
function fcv(v) {{
  if (curMode==='%') {{
    const p = TOTAL>0 ? v/TOTAL*100 : 0;
    return p.toFixed(3)+'%';
  }}
  return '$'+v.toFixed(2);
}}

function render(period){{
  curPeriod = period;
  ['7d','30d','90d'].forEach(p=>{{
    const b=document.getElementById('pnl-btn-'+p);
    if(b) b.className='pnl-period-btn'+(p===period?' pnl-active':'');
  }});

  const raw = period==='7d' ? DAYS.slice(-7) : period==='30d' ? DAYS.slice(-30) : DAYS;
  const rows = period==='90d' ? grp(raw) : raw;

  const tT=raw.reduce((a,d)=>a+d.trading,0);
  const tY=raw.reduce((a,d)=>a+d.yield,0);
  const tC=raw.reduce((a,d)=>a+d.costs,0);
  const tN=tT+tY-tC;
  const hasCostData=raw.some(d=>d.has_cost);
  const nDays = period==='7d'?7:period==='30d'?30:90;

  const modeNote = curMode==='%' ? `van portfolio (${{TOTAL.toFixed(0)}} USDC)` : 'gesloten trades';
  const yDayNote = curMode==='%'
    ? (TOTAL>0?(tY/nDays/TOTAL*100).toFixed(4)+'%/dag':'')
    : (tY/Math.max(nDays,1)).toFixed(2)+'/dag';

  document.getElementById('pnl-summary').innerHTML=`
    <div class="card" style="text-align:center;padding:14px">
      <div style="font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Trading P&L</div>
      <div style="font-size:1.4rem;font-weight:700;color:${{tT>=0?'var(--green)':'var(--red)'}} ">${{fv(tT)}}</div>
      <div style="font-size:.65rem;color:var(--muted);margin-top:2px">${{modeNote}}</div>
    </div>
    <div class="card" style="text-align:center;padding:14px">
      <div style="font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Yield inkomsten</div>
      <div style="font-size:1.4rem;font-weight:700;color:var(--cyan)">+${{fcv(tY)}}</div>
      <div style="font-size:.65rem;color:var(--muted);margin-top:2px">geschat · ${{yDayNote}}</div>
    </div>
    <div class="card" style="text-align:center;padding:14px">
      <div style="font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Kosten</div>
      <div style="font-size:1.4rem;font-weight:700;color:var(--red)">-${{fcv(tC)}}</div>
      <div style="font-size:.65rem;color:var(--muted);margin-top:2px">${{hasCostData?'LLM + infra':'geen data'}}</div>
    </div>
    <div class="card" style="text-align:center;padding:14px;border-color:${{tN>=0?'var(--green)':'var(--red)'}}">
      <div style="font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Netto</div>
      <div style="font-size:1.4rem;font-weight:700;color:${{tN>=0?'var(--green)':'var(--red)'}} ">${{fv(tN)}}</div>
      <div style="font-size:.65rem;color:var(--muted);margin-top:2px">trading + yield - kosten</div>
    </div>`;

  const maxAbs=Math.max(...rows.map(r=>Math.max(Math.abs(r.trading),r.yield,r.costs,0.01)),1);
  let html='<div style="font-size:.72rem">';
  rows.forEach(r=>{{
    const net=r.trading+r.yield-r.costs;
    const tPct=Math.abs(r.trading)/maxAbs*42, yPct=r.yield/maxAbs*42, cPct=r.costs/maxAbs*42;
    const tCol=r.trading>=0?'var(--green)':'var(--red)';
    const nCol=net>=0?'var(--green)':'var(--red)';
    const lbl=(period==='90d'?'W ':'')+r.date.slice(5);
    html+=`<div style="display:flex;align-items:center;gap:6px;padding:3px 0;border-bottom:1px solid rgba(75,85,99,0.12)">
      <div style="width:48px;font-size:.66rem;color:var(--muted);text-align:right;flex-shrink:0">${{lbl}}</div>
      <div style="flex:1;display:flex;align-items:center;gap:2px;min-width:0">
        ${{r.trading!==0?`<div style="width:${{tPct.toFixed(1)}}%;min-width:2px;height:10px;background:${{tCol}};border-radius:2px" title="Trading ${{fv(r.trading)}}"></div>`:''}}
        ${{r.yield>0.005?`<div style="width:${{yPct.toFixed(1)}}%;min-width:2px;height:10px;background:var(--cyan);opacity:.65;border-radius:2px" title="Yield +${{fcv(r.yield)}}"></div>`:''}}
        ${{r.costs>0?`<div style="width:${{cPct.toFixed(1)}}%;min-width:1px;height:6px;background:var(--red);opacity:.4;border-radius:2px" title="Kosten -${{fcv(r.costs)}}"></div>`:''}}
      </div>
      <div style="width:64px;text-align:right;font-size:.7rem;font-weight:600;color:${{nCol}};flex-shrink:0">${{fv(net)}}</div>
    </div>`;
  }});
  html+='</div>';
  document.getElementById('pnl-chart').innerHTML=html;
}}

window.togglePnlMode=function(){{
  curMode = curMode==='$' ? '%' : '$';
  const btn=document.getElementById('pnl-btn-mode');
  if(btn){{
    btn.textContent = curMode==='$' ? '$ bedrag' : '% portfolio';
    btn.className='pnl-period-btn'+(curMode==='%'?' pnl-active':'');
  }}
  render(curPeriod);
}};
window.setPnlPeriod=function(p){{ render(p); }};
document.addEventListener('DOMContentLoaded',()=>render('30d'));
}})();
</script>
"""


def _build_info_block() -> str:
    return """
    <div class="card" style="background:rgba(59,130,246,0.05);border-color:rgba(59,130,246,0.25)">
      <div style="font-size:.85rem;font-weight:600;color:var(--blue);margin-bottom:10px">ℹ️ Hoe werkt dit?</div>
      <div class="two-col" style="font-size:.82rem;color:var(--muted);line-height:1.6">
        <div>
          <strong style="color:var(--text)">Semi-automatisch (actief)</strong><br>
          TreasuryAgent draait elk uur. Jij klikt "Goedkeuren" — de agent voert bridge + Aave deposit automatisch uit.
        </div>
        <div>
          <strong style="color:var(--text)">Signing key</strong><br>
          Arbitrum-transacties worden gesigneerd met <code>HL_VAULT_PRIVATE_KEY</code> (of <code>HL_PRIVATE_KEY</code> als fallback). Zorg dat dit wallet ETH heeft voor gas (&lt;$0.05).
        </div>
        <div>
          <strong style="color:var(--text)">Bridge route</strong><br>
          HL → Arbitrum (native HL bridge, ~15 min) → Aave v3 Arbitrum (seconden). Gas op Arbitrum: &lt;$0.05.
        </div>
        <div>
          <strong style="color:var(--text)">Trading buffer</strong><br>
          Agent houdt altijd 35% van HL-saldo vrij als directe trading margin. Alleen het surplus wordt gedeployed.
        </div>
      </div>
    </div>
    """


# ── Page assembly ─────────────────────────────────────────────────────────────

def build_treasury_html() -> str:
    state     = _load_json("treasury_state.json", {})
    proposals = _load_json("treasury_proposals.json", [])

    hl   = state.get("hl_snapshot", {})
    opps = state.get("opportunities", [])
    ts   = state.get("timestamp", "")[:16].replace("T", " ") + " UTC" if state.get("timestamp") else "—"
    now  = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    pending_count = sum(1 for p in proposals if p.get("status") == "PENDING")
    pending_badge = (
        f'<span style="background:var(--yellow);color:#000;border-radius:10px;font-size:.7rem;padding:2px 8px;font-weight:700;margin-left:8px">{pending_count} te reviewen</span>'
        if pending_count else ""
    )

    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Treasury — Agent Trader</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
<script>
async function approveTreasury(id) {{
  const btn = document.getElementById('btn-' + id);
  if (btn) {{ btn.disabled = true; btn.textContent = 'Bezig…'; }}
  try {{
    const res = await fetch('/api/treasury/approve', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{id}})
    }});
    const data = await res.json();
    if (data.ok) {{
      location.reload();
    }} else {{
      alert('Fout: ' + (data.error || 'onbekend'));
      if (btn) {{ btn.disabled = false; btn.textContent = '✅ Goedkeuren — automatisch uitvoeren'; }}
    }}
  }} catch(e) {{
    alert('Netwerk fout: ' + e);
    if (btn) {{ btn.disabled = false; btn.textContent = '✅ Goedkeuren — automatisch uitvoeren'; }}
  }}
}}
</script>
</head>
<body>
<div class="container">

<header>
  <div class="logo">
    <div class="logo-icon">💰</div>
    <div>
      <h1>Treasury{pending_badge}</h1>
      <div style="font-size:.75rem;color:var(--muted)">Kapitaaloptimalisatie — Agent Trader</div>
    </div>
  </div>
  <div class="header-right">
    <div class="live"><div class="pulse-dot"></div>{now}</div>
    <a href="/" class="nav-back">← Dashboard</a>
    <a href="/performance" class="nav-back">Performance →</a>
  </div>
</header>

<div class="section">
  <div class="section-header">
    <span class="section-title">Portfolio overzicht</span>
    <div class="section-line"></div>
    <span style="font-size:.75rem;color:var(--muted)">TreasuryAgent data: {ts}</span>
  </div>
  {_build_portfolio_overview(state)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Hyperliquid — kapitaalbenutting</span>
    <div class="section-line"></div>
  </div>
  {_build_hl_snapshot(hl)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Yield opportunities — live (DeFiLlama)</span>
    <div class="section-line"></div>
  </div>
  {_build_opportunities(opps)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">P&amp;L overzicht</span>
    <div class="section-line"></div>
  </div>
  {_build_pnl_section(state)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Voorstellen{pending_badge}</span>
    <div class="section-line"></div>
  </div>
  {_build_proposals(proposals)}
</div>

<div class="section">
  <div class="section-header">
    <span class="section-title">Hoe werkt dit?</span>
    <div class="section-line"></div>
  </div>
  {_build_info_block()}
</div>

<footer>
  Auto-refresh elke 5 min &nbsp;|&nbsp; Data: treasury_state.json · treasury_proposals.json
  &nbsp;|&nbsp; <a href="/" style="color:var(--blue)">Dashboard</a>
  &nbsp;|&nbsp; <a href="/performance" style="color:var(--blue)">Performance</a>
</footer>

</div>
</body>
</html>"""
