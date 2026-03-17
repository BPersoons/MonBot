"""
Standalone Dashboard Server
Serves the Swarm Command Center dashboard at /dashboard
Reads agent health data directly from Supabase.
Runs as a background thread inside main.py.
"""
import threading
import logging
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle each HTTP request in a separate thread."""
    daemon_threads = True
from datetime import datetime

logger = logging.getLogger(__name__)

DASHBOARD_PORT = 8080

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="30">
<title>Swarm Command Center | Agent Trader</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
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
.tabs{display:flex;gap:10px;margin-bottom:24px}
.tab-btn{background:rgba(255,255,255,0.05);border:1px solid var(--border);color:var(--muted);padding:10px 20px;border-radius:8px;cursor:pointer;font-weight:600;transition:all 0.2s}
.tab-btn:hover{background:rgba(255,255,255,0.1);color:var(--text)}
.tab-btn.active{background:var(--blue);color:white;border-color:var(--blue)}
.tab-content{display:none}
.tab-content.active{display:block}

/* Existing Styles */
.section{margin-bottom:32px}
.section-header{display:flex;align-items:center;gap:10px;margin-bottom:16px}
.section-title{font-size:1rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px}
.section-line{flex:1;height:1px;background:var(--border)}
.section-badge{font-size:.7rem;padding:3px 8px;border-radius:8px;background:rgba(59,130,246,0.15);color:var(--blue)}
.pipeline-flow{display:flex;align-items:center;gap:6px;margin-bottom:16px;padding:10px 16px;background:rgba(59,130,246,0.05);border-radius:10px;border:1px solid rgba(59,130,246,0.15);overflow-x:auto;flex-wrap:wrap}
.flow-step{font-size:.75rem;color:var(--muted);white-space:nowrap;padding:4px 8px;border-radius:6px;transition:all .2s}
.flow-arrow{color:rgba(59,130,246,0.5);font-size:.75rem}
.flow-active{color:var(--green);font-weight:600;background:rgba(16,185,129,0.1)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px}
.card{background:var(--card);backdrop-filter:blur(10px);border:1px solid var(--border);border-radius:16px;padding:24px;position:relative;transition:transform .2s,box-shadow .2s}
.card:hover{transform:translateY(-2px);box-shadow:0 8px 32px rgba(0,0,0,0.3)}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.card.ACTIVE::before{background:var(--green)}
.card.WORKING::before{background:var(--cyan);animation:shimmer 1.5s infinite}
@keyframes shimmer{0%,100%{opacity:1}50%{opacity:.5}}
.card.ERROR::before{background:var(--red)}
.card.IDLE::before{background:var(--yellow)}
.card.STARTING::before{background:var(--blue)}
.agent-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.agent-name{font-size:1.125rem;font-weight:600;display:flex;align-items:center;gap:6px}
.step-num{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:rgba(59,130,246,0.2);color:var(--blue);font-size:.7rem;font-weight:700;flex-shrink:0}
.agent-desc{font-size:.7rem;color:var(--muted);margin-bottom:14px;line-height:1.3}
.info-icon{cursor:pointer;font-size:.8rem;color:var(--muted);opacity:.6;transition:opacity .2s}
.info-icon:hover{opacity:1}
.badge{padding:4px 10px;border-radius:20px;font-size:.75rem;font-weight:500;text-transform:uppercase;display:flex;align-items:center;gap:6px}
.badge.ACTIVE{background:rgba(16,185,129,0.2);color:var(--green)}
.badge.WORKING{background:rgba(6,182,212,0.2);color:var(--cyan)}
.badge.ERROR{background:rgba(239,68,68,0.2);color:var(--red)}
.badge.IDLE{background:rgba(245,158,11,0.2);color:var(--yellow)}
.badge.STARTING{background:rgba(59,130,246,0.2);color:var(--blue)}
.dot{width:8px;height:8px;border-radius:50%;background:currentColor}
.stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.stats-2{grid-template-columns:1fr 1fr}
.stat{padding:10px;background:rgba(0,0,0,0.3);border-radius:8px}
.stat-label{font-size:.7rem;color:var(--muted);margin-bottom:3px;text-transform:uppercase;letter-spacing:.5px}
.stat-value{font-size:1rem;font-weight:600}
.stat-value.small{font-size:.85rem}
.task-box{font-size:.8rem;color:var(--cyan);margin-top:12px;padding:10px 12px;background:rgba(6,182,212,0.08);border-radius:8px;border-left:3px solid var(--cyan);line-height:1.4}
.task-box .label{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.activity-box{font-size:.75rem;color:var(--muted);margin-top:8px;padding:8px 10px;background:rgba(255,255,255,0.03);border-radius:6px;line-height:1.4}
.activity-box .label{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
.error-msg{font-size:.75rem;color:var(--red);margin-top:8px;padding:8px 10px;background:rgba(239,68,68,0.1);border-radius:6px}
.calls-tag{display:inline-block;font-size:.65rem;padding:2px 7px;border-radius:4px;background:rgba(139,92,246,0.15);color:var(--purple);margin-right:4px;margin-bottom:4px}
.calls-row{margin-top:10px;display:flex;flex-wrap:wrap;gap:2px}
.calls-label{font-size:.65rem;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px}
.tooltip-wrap{position:relative;display:inline-block}
.tooltip-content{display:none;position:absolute;z-index:100;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);background:#1e293b;border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:280px;max-width:340px;box-shadow:0 8px 24px rgba(0,0,0,0.4);font-size:.75rem;line-height:1.5;color:var(--text)}
.tooltip-wrap:hover .tooltip-content{display:block}
.tooltip-content .tt-title{font-weight:600;margin-bottom:6px;color:var(--cyan);font-size:.8rem}
.tooltip-content .tt-section{margin-top:8px}
.tooltip-content .tt-label{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:3px}
.tooltip-content .tt-item{padding:2px 0;color:var(--text)}
.uptime-tip{position:relative;cursor:help;border-bottom:1px dotted var(--muted)}
.uptime-tip:hover::after{content:attr(data-tip);position:absolute;bottom:120%;left:50%;transform:translateX(-50%);background:#1f2937;color:var(--text);padding:6px 10px;border-radius:6px;font-size:.7rem;white-space:nowrap;z-index:10;box-shadow:0 4px 12px rgba(0,0,0,0.3)}
footer{text-align:center;padding:24px;color:var(--muted);font-size:.875rem;border-top:1px solid var(--border);margin-top:32px}

/* Health Monitor Styles */
.monitor-ok{padding:20px 24px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);border-radius:12px;display:flex;align-items:center;gap:12px;margin-bottom:24px;font-weight:600;color:var(--green);font-size:1rem}
.monitor-ok .big-check{font-size:2rem}
.issues-table{width:100%;border-collapse:collapse;font-size:.82rem}
.issues-table th{text-align:left;padding:10px 12px;font-size:.65rem;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);border-bottom:1px solid var(--border);background:rgba(0,0,0,0.2)}
.issues-table td{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,0.04);vertical-align:top}
.issues-table tr:hover{background:rgba(255,255,255,0.03)}
.sev-badge{display:inline-block;padding:3px 8px;border-radius:8px;font-size:.7rem;font-weight:600;text-transform:uppercase}
.sev-badge.HIGH{background:rgba(239,68,68,0.2);color:var(--red)}
.sev-badge.MEDIUM{background:rgba(245,158,11,0.2);color:var(--yellow)}
.sev-badge.LOW{background:rgba(59,130,246,0.2);color:var(--blue)}
.monitor-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}
.mstat{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center}
.mstat .big{font-size:1.6rem;font-weight:700}
.mstat .lbl{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
.issue-detail{font-family:monospace;font-size:.75rem;color:var(--muted);margin-top:4px;padding:6px 8px;background:rgba(0,0,0,0.3);border-radius:4px;white-space:pre-wrap;word-break:break-all;max-height:100px;overflow-y:auto}
/* Decision Cards */
.decision-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:12px;border-left:4px solid var(--muted);transition:transform .2s}
.decision-card:hover{transform:translateX(3px)}
.decision-card.BUY,.decision-card.LONG{border-left-color:var(--green)}
.decision-card.SELL,.decision-card.SHORT{border-left-color:var(--red)}
.decision-card.NO_GO,.decision-card.SKIP{border-left-color:var(--muted)}
.decision-card.MONITOR{border-left-color:var(--yellow)}
.dec-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.dec-ticker{font-size:1.15rem;font-weight:700}
.dec-verdict{padding:5px 14px;border-radius:20px;font-size:.8rem;font-weight:700;text-transform:uppercase}
.dec-verdict.BUY,.dec-verdict.LONG{background:rgba(16,185,129,0.2);color:var(--green)}
.dec-verdict.SELL,.dec-verdict.SHORT{background:rgba(239,68,68,0.2);color:var(--red)}
.dec-verdict.NO_GO,.dec-verdict.SKIP{background:rgba(156,163,175,0.2);color:var(--muted)}
.dec-verdict.MONITOR{background:rgba(245,158,11,0.2);color:var(--yellow)}
.dec-reason{font-size:.9rem;line-height:1.5;color:var(--text);margin-bottom:12px}
.dec-cases{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.dec-case{padding:12px;border-radius:8px;font-size:.8rem;line-height:1.4}
.dec-case.bull{background:rgba(16,185,129,0.06);border:1px solid rgba(16,185,129,0.15)}
.dec-case.bear{background:rgba(239,68,68,0.06);border:1px solid rgba(239,68,68,0.15)}
.dec-case strong{display:block;margin-bottom:4px}
.dec-next{font-size:.8rem;padding:8px 12px;background:rgba(6,182,212,0.08);border-left:3px solid var(--cyan);border-radius:0 6px 6px 0;color:var(--cyan)}
/* Opportunity Cards */
.opp-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:12px;border-left:4px solid var(--yellow)}
.opp-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.opp-ticker{font-size:1.1rem;font-weight:700}
.opp-time{font-size:.75rem;color:var(--muted)}
.opp-status{font-size:.85rem;line-height:1.5;color:var(--text);margin-bottom:10px}
.prob-bar{height:8px;border-radius:4px;background:rgba(255,255,255,0.1);overflow:hidden;margin-top:6px}
.prob-fill{height:100%;border-radius:4px;transition:width .3s}
.prob-label{display:flex;justify-content:space-between;font-size:.7rem;color:var(--muted);margin-top:3px}
/* Health Banner */
.health-strip{display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:.85rem;font-weight:600;cursor:pointer;transition:opacity .2s}
.health-strip:hover{opacity:.85}
.health-strip.ok{background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.25);color:var(--green)}
.health-strip.warn{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.25);color:var(--red)}
.health-strip.boot{background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.25);color:var(--yellow)}
/* Scout summary strip */
.scout-strip{display:flex;align-items:center;gap:16px;padding:10px 16px;border-radius:10px;margin-bottom:16px;background:rgba(6,182,212,0.06);border:1px solid rgba(6,182,212,0.15);font-size:.85rem}
.scout-link{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:6px;background:rgba(6,182,212,0.15);color:var(--cyan);font-size:.7rem;cursor:pointer;text-decoration:none;transition:all .2s}
.scout-link:hover{background:rgba(6,182,212,0.3)}
.scout-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:20px}
.scout-stat{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px;text-align:center}
.scout-stat .big{font-size:1.8rem;font-weight:700}
.scout-stat .lbl{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
.scan-table{width:100%;border-collapse:collapse;font-size:.8rem}
.scan-table th{text-align:left;padding:10px 8px;font-size:.65rem;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);border-bottom:1px solid var(--border);background:rgba(0,0,0,0.2)}
.scan-table td{padding:10px 8px;border-bottom:1px solid rgba(255,255,255,0.04)}
.scan-table tr:hover{background:rgba(255,255,255,0.03)}
.scan-table tr.approved{border-left:3px solid var(--green)}
.scan-table tr.rejected{border-left:3px solid var(--red)}
.scan-table tr.skipped{border-left:3px solid var(--yellow);opacity:.6}
.scan-table tr.monitored{border-left:3px solid var(--cyan)}
.tip{position:relative;cursor:help}
.tip .tip-text{visibility:hidden;opacity:0;position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);background:var(--card);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:.7rem;font-weight:400;line-height:1.5;white-space:normal;width:260px;z-index:100;pointer-events:none;transition:opacity .15s;box-shadow:0 4px 16px rgba(0,0,0,0.4)}
.tip .tip-text::after{content:'';position:absolute;top:100%;left:50%;transform:translateX(-50%);border:6px solid transparent;border-top-color:var(--border)}
.tip:hover .tip-text{visibility:visible;opacity:1}
.status-pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.65rem;font-weight:600}
.status-pill.APPROVED{background:rgba(16,185,129,0.15);color:var(--green)}
.status-pill.REJECTED{background:rgba(239,68,68,0.15);color:var(--red)}
.status-pill.SKIPPED{background:rgba(245,158,11,0.15);color:var(--yellow)}
.status-pill.MONITORED{background:rgba(6,182,212,0.15);color:var(--cyan)}
.scout-config{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:20px}
.scout-config h3{font-size:.85rem;font-weight:600;margin-bottom:10px;color:var(--cyan)}
.scout-config ul{list-style:none;padding:0}
.scout-config li{padding:4px 0;font-size:.8rem;color:var(--muted)}
.scout-config li::before{content:'▸ ';color:var(--cyan)}
.explainer-card{background:linear-gradient(135deg,rgba(59,130,246,0.1),rgba(139,92,246,0.1));border:1px solid var(--blue);border-radius:12px;padding:20px;margin-bottom:24px}
.explainer-title{font-size:1.1rem;font-weight:700;color:var(--blue);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.explainer-text{font-size:.9rem;line-height:1.6;color:var(--text)}
.explainer-tag{display:inline-block;background:rgba(59,130,246,0.2);color:var(--blue);padding:2px 8px;border-radius:4px;font-size:.8rem;font-weight:600;margin:0 4px}
.results-table{width:100%;border-collapse:collapse;margin-top:20px;font-size:.9rem}
.results-table th{text-align:left;padding:12px;color:var(--muted);border-bottom:1px solid var(--border);font-size:.75rem;text-transform:uppercase}
.results-table td{padding:12px;border-bottom:1px solid rgba(255,255,255,0.05)}
.res-val{font-family:monospace;font-weight:600}
.good{color:var(--green)}
.bad{color:var(--red)}
.neutral{color:var(--muted)}
/* CPO Vision Styles */
.cpo-grid{display:flex;flex-direction:column;gap:16px;margin-top:16px}
.cpo-card{background:var(--card);border:1px solid var(--border);border-left:4px solid var(--border);border-radius:12px;padding:20px;transition:transform 0.2s}
.cpo-card:hover{transform:translateX(4px);border-color:var(--blue)}
.cpo-card.HIGH{border-left-color:var(--red)}
.cpo-card.MID{border-left-color:var(--yellow)}
.cpo-card.LOW{border-left-color:var(--blue)}
.cpo-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}
.cpo-title{font-size:1.1rem;font-weight:600;color:var(--text)}
.cpo-meta{display:flex;gap:8px;font-size:0.75rem}
.cpo-desc{font-size:0.9rem;color:var(--muted);line-height:1.5;white-space:pre-wrap}
.cpo-prompt-box{margin-top:16px;background:rgba(0,0,0,0.4);border:1px dashed var(--cyan);border-radius:8px;padding:16px}
.cpo-prompt-title{font-size:0.75rem;color:var(--cyan);text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;font-weight:600;display:flex;align-items:center;gap:6px}
.cpo-prompt-text{font-family:monospace;font-size:0.85rem;color:#e2e8f0;white-space:pre-wrap;word-break:break-all}
/* Activity Feed Styles */
.af-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:24px}
.af-stat{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px;text-align:center}
.af-stat .big{font-size:1.6rem;font-weight:700}
.af-stat .lbl{font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:4px}
.af-event{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:8px;border-left:4px solid var(--muted);transition:transform .15s}
.af-event:hover{transform:translateX(3px)}
.af-event.DECISION{border-left-color:var(--blue)}
.af-event.NARRATOR_CHECK{border-left-color:var(--purple)}
.af-event.RISK_CHECK{border-left-color:var(--cyan)}
.af-event.EXECUTION{border-left-color:var(--green)}
.af-event.TRADE_EXIT{border-left-color:var(--yellow)}
.af-event.MONITOR_EXPIRED{border-left-color:var(--red)}
.af-event.MONITOR_UPDATE{border-left-color:var(--yellow)}
.af-badge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:.65rem;font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.af-badge.DECISION{background:rgba(59,130,246,0.15);color:var(--blue)}
.af-badge.NARRATOR_CHECK{background:rgba(139,92,246,0.15);color:var(--purple)}
.af-badge.RISK_CHECK{background:rgba(6,182,212,0.15);color:var(--cyan)}
.af-badge.EXECUTION{background:rgba(16,185,129,0.15);color:var(--green)}
.af-badge.TRADE_EXIT{background:rgba(245,158,11,0.15);color:var(--yellow)}
.af-badge.MONITOR_EXPIRED{background:rgba(239,68,68,0.15);color:var(--red)}
.af-badge.MONITOR_UPDATE{background:rgba(245,158,11,0.15);color:var(--yellow)}
.af-time{font-size:.7rem;color:var(--muted)}
.af-summary-line{font-size:.9rem;color:var(--text);margin:6px 0}
.af-details{font-size:.8rem;color:var(--muted);margin-top:8px;padding:10px;background:rgba(0,0,0,0.3);border-radius:6px;font-family:monospace;white-space:pre-wrap;word-break:break-all}
.af-journey{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:12px}
.af-journey summary{cursor:pointer;font-weight:600;font-size:1rem;color:var(--text)}
.af-journey summary:hover{color:var(--cyan)}
.af-dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
.af-dot.DECISION{background:var(--blue)}
.af-dot.NARRATOR_CHECK{background:var(--purple)}
.af-dot.RISK_CHECK{background:var(--cyan)}
.af-dot.EXECUTION{background:var(--green)}
.af-dot.TRADE_EXIT{background:var(--yellow)}
.af-dot.MONITOR_EXPIRED{background:var(--red)}

/* ── Mobile responsive ───────────────────────────────────────────────── */
@media (max-width:640px){
  .container{padding:12px}
  header{flex-direction:column;align-items:flex-start;gap:10px;margin-bottom:16px;padding-bottom:16px}
  h1{font-size:1.25rem}
  .logo-icon{width:36px;height:36px;font-size:18px}

  /* Tabs: horizontal scroll strip, no wrapping */
  .tabs{overflow-x:auto;flex-wrap:nowrap;padding-bottom:6px;gap:6px;-webkit-overflow-scrolling:touch;scrollbar-width:none}
  .tabs::-webkit-scrollbar{display:none}
  .tab-btn{white-space:nowrap;padding:8px 14px;font-size:.8rem}

  /* Agent grid: single column */
  .grid{grid-template-columns:1fr}
  .card{padding:16px}
  .stats{grid-template-columns:1fr 1fr}

  /* Decision cards */
  .dec-cases{grid-template-columns:1fr}
  .dec-header{flex-wrap:wrap;gap:6px}
  .decision-card{padding:14px}

  /* Opportunity cards */
  .opp-header{flex-wrap:wrap;gap:6px}

  /* Section headers */
  .section-title{font-size:.8rem}

  /* Open positions & history tables: force horizontal scroll */
  table{font-size:.75rem}
  th,td{padding:6px 8px !important;white-space:nowrap}

  /* Stats bar in trades tab */
  div[style*="display:flex"][style*="gap:28px"]{gap:16px !important;flex-wrap:wrap}

  /* Pagination buttons */
  #hist-prev,#hist-next{padding:6px 12px;font-size:.82rem}

  /* CPO cards */
  .cpo-header{flex-direction:column;gap:6px}
  .cpo-meta{flex-wrap:wrap}

  footer{padding:16px;font-size:.75rem}
}
</style>
<script>
    document.addEventListener("DOMContentLoaded", () => {
        const activeTab = sessionStorage.getItem('activeTab') || 'pulse';
        showTab(activeTab);
    });

    function showTab(id) {
        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        document.getElementById('tab-' + id).classList.add('active');
        document.getElementById('btn-' + id).classList.add('active');
        sessionStorage.setItem('activeTab', id);
    }
    // Auto-refresh every 30 seconds
    setInterval(() => window.location.reload(), 30000);
</script>
</head>
<body>
<div class="container">
<header>
<div class="logo">
<div class="logo-icon">&#x1F3AF;</div>
<div>
<h1>Swarm Command Center</h1>
<span style="color:var(--muted);font-size:.875rem">Agent Trader v1.0</span>
</div>
</div>
<div class="live">
<div class="pulse-dot"></div>
<span>Live &bull; {timestamp}</span>
</div>
</header>

<div class="tabs">
    <div id="btn-pulse" class="tab-btn active" onclick="showTab('pulse')">&#x26A1; Swarm Dashboard</div>
    <div id="btn-cpo" class="tab-btn" onclick="showTab('cpo')">&#x1F4A1; ProductOwner</div>
    <div id="btn-decisions" class="tab-btn" onclick="showTab('decisions')">&#x1F4CB; ProjectLead</div>
    <div id="btn-learner" class="tab-btn" onclick="showTab('learner')">&#x1F52C; Insights</div>
    <div id="btn-trades" class="tab-btn" onclick="showTab('trades')">&#x1F4B0; Trades</div>
</div>

<!-- PULSE TAB -->
<div id="tab-pulse" class="tab-content active">
    {health_banner}
    {pipeline_section}
    {opportunities_section}
    {supporting_section}
    {llm_stats_section}
</div>

<!-- DECISIONS TAB -->
<div id="tab-decisions" class="tab-content">
    {decisions_section}
</div>

<!-- CPO TAB -->
<div id="tab-cpo" class="tab-content">
    {cpo_section}
</div>

<!-- SWARM LEARNER TAB -->
<div id="tab-learner" class="tab-content">
    {learner_section}
</div>

<!-- TRADES TAB -->
<div id="tab-trades" class="tab-content">
    {trades_section}
</div>

<footer>
<p>&#x1F680; Powered by Agent Trader Swarm &bull; Supabase &bull; Hyperliquid</p>
<p style="margin-top:8px;font-size:.75rem">Auto-refresh every 30 seconds (Pulse Tab only)</p>
</footer>
</div>
</body>
</html>"""

ICONS = {
    "ProjectLead": "&#x1F3AF;", "Heartbeat": "&#x2764;&#xFE0F;",
    "Scout": "&#x1F52C;", "PerformanceAuditor": "&#x1F4CB;",
    "ProductOwner": "&#x1F454;", "Judge": "&#x2696;&#xFE0F;",
    "ExecutionAgent": "&#x26A1;", "RiskManager": "&#x1F6E1;&#xFE0F;",
    "TechnicalAnalyst": "&#x1F4C8;", "FundamentalAnalyst": "&#x1F4CA;",
    "SentimentAnalyst": "&#x1F4AC;", "Auditor": "&#x1F6E1;&#xFE0F;",
    "CPO": "&#x1F454;", "ResearchAgent": "&#x1F52C;",
    "SwarmMonitor": "&#x1F50D;",
}

# Pipeline lineage: agents in execution order within the main loop
PIPELINE_ORDER = [
    "Heartbeat",
    "Scout",
    "ProjectLead",
    "PerformanceAuditor",
    "ProductOwner",
]

PIPELINE_LABELS = {
    "Heartbeat": "System Pulse",
    "Scout": "Market Scan",
    "ProjectLead": "Analysis",
    "PerformanceAuditor": "Audit",
    "ProductOwner": "CPO Review",
}

# Agent descriptions: short summary + config/rules + which sub-agents they call
AGENT_INFO = {
    "Heartbeat": {
        "desc": "System uptime monitor. Ticks every ~60s to confirm the trading pipeline is alive.",
        "config": ["Frequency: every loop iteration (~60s)", "Reports: stdout tail + cycle metadata"],
        "rules": ["Always runs, even during errors", "Counter = system uptime, not pipeline cycles"],
        "calls": [],
    },
    "Scout": {
        "desc": "Market scanner. Scans Hyperliquid universe (USDC pairs), backtests candidates, and proposes opportunities.",
        "config": ["Source: Hyperliquid (ccxt)", "Scan: top 20 by volume", "Backtest: AutoBacktester (30d, 1h candles)"],
        "rules": ["Min volume: $100K daily", "Backtest: PnL > 0% AND trades >= 2", "Excludes stablecoins & special tokens"],
        "calls": [],
    },
    "ProjectLead": {
        "desc": "Chief orchestrator. Gathers signals from 3 analysts, runs LLM Council Debate, and routes to execution.",
        "config": ["Weighted scoring: Tech/Fund/Sent", "LLM: Gemini Council Debate", "Threshold: > 0.5 (LONG), < -0.5 (SHORT)"],
        "rules": ["Processes each active ticker sequentially", "Sends to RiskManager before execution", "Can veto low-score proposals"],
        "calls": ["TechnicalAnalyst", "FundamentalAnalyst", "SentimentAnalyst", "RiskManager", "ExecutionAgent"],
    },
    "TechnicalAnalyst": {
        "desc": "Chart analyst. Uses Multi-Timeframe Analysis (4h/1h/15m) to generate technical signal scores.",
        "config": ["Exchange: Hyperliquid (ccxt)", "Timeframes: 4h (50%), 1h (30%), 15m (20%)", "Indicators: RSI(14), EMA(20/50)"],
        "rules": ["Score range: -1.0 to +1.0", "RSI>70 = overbought (-0.3)", "RSI<30 = oversold (+0.3)", "EMA20>EMA50 = bullish (+0.4)"],
        "calls": [],
        "called_by": "ProjectLead",
    },
    "FundamentalAnalyst": {
        "desc": "Macro analyst. Evaluates on-chain data (whale alerts), ETF flows, and macro indicators with time decay.",
        "config": ["Data: Whale alerts, ETF flows, CPI/rates", "Decay: 1/(1+0.1*days_old)"],
        "rules": ["Score range: -1.0 to +1.0", "Weighs recent events higher", "Per-asset customization"],
        "calls": [],
        "called_by": "ProjectLead",
    },
    "SentimentAnalyst": {
        "desc": "Social intelligence. Scrapes Twitter/Reddit/News, filters noise, and uses LLM to score sentiment.",
        "config": ["Sources: WebIntelligence (Bing)", "LLM: Gemini sentiment scoring", "Staleness: 15min refresh"],
        "rules": ["Score range: -1.0 to +1.0", "Filters: dedup, min 15 chars, <5 hashtags", "Ignores: giveaway/airdrop spam"],
        "calls": [],
        "called_by": "ProjectLead",
    },
    "RiskManager": {
        "desc": "Risk gatekeeper. Validates trades using Kelly Criterion, anomaly detection, and circuit breakers.",
        "config": ["Kelly Criterion: f*=(bp-q)/b", "Max position: 20% of bankroll", "Circuit breaker: integrated"],
        "rules": ["Sharpe ratio must be > 1.5", "Kelly fraction must be > 0", "Anomaly check: corrupt data, outliers", "Flash crash detection"],
        "calls": [],
        "called_by": "ProjectLead",
    },
    "ExecutionAgent": {
        "desc": "Trade executor. Executes orders on Hyperliquid L1 with Human-in-the-Loop approval for large trades.",
        "config": ["Exchange: Hyperliquid L1", "HITL threshold: $1000", "Approval: Supabase + Telegram"],
        "rules": ["Trades >$1000 require founder approval", "Pre-flight: staleness + slippage check", "Auto-expire: 24h timeout", "Logs all trades to Supabase"],
        "calls": [],
        "called_by": "ProjectLead",
    },
    "Judge": {
        "desc": "Trade validator. Reviews proposals against risk criteria before allowing execution.",
        "config": ["Validation: score threshold check"],
        "rules": ["Can reject low-confidence proposals", "Works with RiskManager output"],
        "calls": [],
    },
    "Auditor": {
        "desc": "System auditor. Performs governance checks on the trading pipeline.",
        "config": ["Runs: per pipeline cycle"],
        "rules": ["Reviews trade log integrity", "Checks for anomalies"],
        "calls": [],
    },
    "SwarmMonitor": {
        "desc": "Proactive watchdog. Checks every 5 min for stale agents, ERROR states, frozen cycles, and log errors.",
        "config": ["Check interval: 5 min", "Stale threshold: 10 min", "Log scan: last 100 lines", "Telegram alerts: deduped, 30 min cooldown"],
        "rules": ["Monitors: Heartbeat, Scout, ProjectLead, PerformanceAuditor, ProductOwner", "Flags: ERROR status, stale pulse, frozen cycle count, log ERROR/CRITICAL/Traceback"],
        "calls": [],
    },
}


def _fmt_pulse(raw):
    """Format a pulse timestamp to readable time."""
    if not raw:
        return "N/A"
    try:
        dt = datetime.fromisoformat(raw.replace("+00:00", "").replace("Z", ""))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return raw[:19] if raw else "N/A"


def _fmt_duration(seconds):
    """Format seconds into human readable duration."""
    if seconds is None:
        return "---"
    s = float(seconds)
    if s < 60:
        return f"{s:.0f}s"
    elif s < 3600:
        return f"{s/60:.1f}m"
    else:
        return f"{s/3600:.1f}h"


def _build_tooltip(name):
    """Build hover tooltip HTML for an agent."""
    info = AGENT_INFO.get(name)
    if not info:
        return ""

    config_html = "".join(f'<div class="tt-item">&bull; {c}</div>' for c in info.get("config", []))
    rules_html = "".join(f'<div class="tt-item">&bull; {r}</div>' for r in info.get("rules", []))

    calls = info.get("calls", [])
    calls_html = ""
    if calls:
        tags = "".join(f'<span class="calls-tag">{ICONS.get(c, "")} {c}</span>' for c in calls)
        calls_html = f'<div class="tt-section"><div class="tt-label">Calls</div>{tags}</div>'

    called_by = info.get("called_by", "")
    called_html = ""
    if called_by:
        called_html = f'<div class="tt-section"><div class="tt-label">Called by</div><div class="tt-item">{ICONS.get(called_by, "")} {called_by}</div></div>'

    return f'''<div class="tooltip-content">
        <div class="tt-title">{ICONS.get(name, "")} {name}</div>
        <div class="tt-section"><div class="tt-label">Configuration</div>{config_html}</div>
        <div class="tt-section"><div class="tt-label">Rules</div>{rules_html}</div>
        {calls_html}
        {called_html}
    </div>'''


def _build_calls_row(name):
    """Build the 'Calls' badge row for pipeline agents that orchestrate sub-agents."""
    info = AGENT_INFO.get(name, {})
    calls = info.get("calls", [])
    if not calls:
        return ""
    tags = "".join(f'<span class="calls-tag">{ICONS.get(c, "")} {c}</span>' for c in calls)
    return f'<div class="calls-row"><div class="calls-label">Orchestrates</div><br>{tags}</div>'


def _build_agent_card(a, step_num=None):
    """Build HTML for a single agent card."""
    name = a.get("agent_name", "Unknown")
    status = a.get("status", "IDLE")
    pulse = _fmt_pulse(a.get("last_pulse", ""))
    cycles = a.get("cycle_count", 0)
    meta = a.get("metadata") or {}
    error = a.get("last_error", "")
    icon = ICONS.get(name, "&#x1F916;")

    # Agent info
    info = AGENT_INFO.get(name, {})
    desc = info.get("desc", "")

    # Determine if this is an uptime ticker (Heartbeat)
    is_heartbeat = meta.get("type") == "uptime_tick" or name == "Heartbeat"
    cycle_label = '<span class="uptime-tip" data-tip="Uptime ticks (every ~60s)">Uptime Ticks</span>' if is_heartbeat else "Cycles"

    # Step number badge for pipeline agents
    step_badge = f'<span class="step-num">{step_num}</span>' if step_num else ""

    # Tooltip
    tooltip_html = _build_tooltip(name)
    if name == "Scout":
        info_icon = '<div class="scout-link" onclick="showTab(\'scout\')">&#x1F52C; View Intel</div>'
    else:
        info_icon = f'<span class="tooltip-wrap"><span class="info-icon">&#x2139;&#xFE0F;</span>{tooltip_html}</span>' if tooltip_html else ""

    # Extract enriched metadata
    current_task = meta.get("current_task", "")
    last_activity = meta.get("last_activity", "")
    cycle_duration = meta.get("cycle_duration_s")
    research_duration = meta.get("research_duration_s")
    duration_val = cycle_duration or research_duration

    # Build stats row
    duration_stat = ""
    if duration_val is not None:
        dur_label = "Cycle Time" if cycle_duration else "Scan Time"
        duration_stat = f'<div class="stat"><div class="stat-label">{dur_label}</div><div class="stat-value small">{_fmt_duration(duration_val)}</div></div>'
        stats_class = "stats"
    else:
        stats_class = "stats stats-2"

    stats_html = f'''<div class="{stats_class}">
        <div class="stat"><div class="stat-label">Last Pulse</div><div class="stat-value small">{pulse}</div></div>
        <div class="stat"><div class="stat-label">{cycle_label}</div><div class="stat-value">{cycles}</div></div>
        {duration_stat}
    </div>'''

    # Task box
    task_html = ""
    if current_task:
        task_html = f'<div class="task-box"><div class="label">Current Task</div>{current_task}</div>'

    # Activity box
    activity_html = ""
    if last_activity:
        activity_html = f'<div class="activity-box"><div class="label">Last Activity</div>{last_activity}</div>'

    # Error box
    error_html = ""
    if error:
        error_html = f'<div class="error-msg">&#x26A0;&#xFE0F; {error}</div>'

    # Calls row (which sub-agents does this pipeline agent call)
    calls_html = _build_calls_row(name)

    # Description line
    desc_html = f'<div class="agent-desc">{desc}</div>' if desc else ""

    # Called-by badge for supporting agents
    called_by = info.get("called_by", "")
    called_by_html = ""
    if called_by:
        called_by_html = f'<div class="calls-row"><div class="calls-label">Called by</div><br><span class="calls-tag">{ICONS.get(called_by, "")} {called_by}</span></div>'

    return f'''<div class="card {status}">
    <div class="agent-header">
        <span class="agent-name">{step_badge}{icon} {name} {info_icon}</span>
        <span class="badge {status}"><span class="dot"></span>{status}</span>
    </div>
    {desc_html}
    {stats_html}
    {task_html}
    {activity_html}
    {error_html}
    {calls_html}
    {called_by_html}
</div>'''


def _build_scout_section(agent):
    """Build the dedicated Scout Intel tab section."""
    if not agent:
        return '<div class="section"><div class="error-msg">Scout agent not found (offline?)</div></div>'
        
    meta = agent.get("metadata") or {}
    scan_results = meta.get("scan_results", [])
    
    # 1. Stats Cards
    total = meta.get("total_universe", len(scan_results))
    approved = meta.get("approved_count", 0)
    monitored = meta.get("monitored_count", 0)
    rejected = meta.get("rejected_count", 0)
    skipped = meta.get("skipped_count", 0)
    
    stats_html = f'''<div class="scout-summary">
        <div class="scout-stat"><div class="big">{total}</div><div class="lbl">Total Scanned</div></div>
        <div class="scout-stat"><div class="big" style="color:var(--green)">{approved}</div><div class="lbl">Approved</div></div>
        <div class="scout-stat"><div class="big" style="color:var(--cyan)">{monitored}</div><div class="lbl">Monitored</div></div>
        <div class="scout-stat"><div class="big" style="color:var(--red)">{rejected}</div><div class="lbl">Rejected</div></div>
        <div class="scout-stat"><div class="big" style="color:var(--yellow)">{skipped}</div><div class="lbl">Skipped</div></div>
    </div>'''

    # 2. Config Card
    info = AGENT_INFO.get("Scout", {})
    config_items = "".join(f'<li>{c}</li>' for c in info.get("config", []))
    rules_items = "".join(f'<li>{r}</li>' for r in info.get("rules", []))
    
    config_html = f'''<div class="scout-config">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
            <div>
                <h3>Configuration</h3>
                <ul>{config_items}</ul>
            </div>
            <div>
                <h3>Active Rules</h3>
                <ul>{rules_items}</ul>
            </div>
        </div>
    </div>'''
    
    # 3. Scan Results Table
    rows = []
    if not scan_results:
        rows.append('<tr><td colspan="9" style="text-align:center;padding:20px;color:var(--muted)">No scan data available yet. Waiting for next cycle...</td></tr>')
    else:
        for r in scan_results:
            status = r.get("status", "UNKNOWN")
            pnl = r.get("pnl", 0)
            trade_count = r.get("trades", 0)
            wr = r.get("win_rate", 0)
            vol = r.get("volume_m", 0)
            
            pnl_color = "var(--green)" if pnl > 0 else ("var(--red)" if pnl < 0 else "var(--muted)")
            
            rows.append(f'''<tr class="{status.lower()}">
                <td style="font-weight:600;color:var(--cyan)">{r.get('ticker')}</td>
                <td>${vol:.1f}M</td>
                <td style="color:{pnl_color};font-weight:bold">{pnl:+.2f}%</td>
                <td>{trade_count}</td>
                <td>{wr:.0%}</td>
                <td>{r.get('volatility',0):.2f}%</td>
                <td><span class="status-pill {status}">{status}</span></td>
                <td style="color:var(--muted);font-style:italic">{r.get('reason')}</td>
                <td style="color:var(--muted)">{datetime.now().strftime("%H:%M")}</td>
            </tr>''')
            
    table_html = f'''<div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F4D1; Scan Results Log</span>
            <span class="section-badge">{len(scan_results)} items</span>
            <span class="section-line"></span>
        </div>
        <div class="card" style="padding:0;overflow:hidden">
            <table class="scan-table">
                <thead>
                    <tr>
                        <th>Ticker</th>
                        <th>Volume</th>
                        <th>Backtest PnL</th>
                        <th>Trades</th>
                        <th>Win Rate</th>
                        <th>Volatility</th>
                        <th>Status</th>
                        <th>Reason</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(rows)}
                </tbody>
            </table>
        </div>
    </div>'''

    return stats_html + config_html + table_html


def _build_cpo_section(backlog_items):
    """Build the product backlog UI section showing CPO ideas."""
    if not backlog_items:
         return '''<div class="explainer-card">
            <div class="explainer-title">&#x1F4A1; CPO Vision Board</div>
            <div class="explainer-text">The Product Owner is analyzing logs. No backlog items generated yet.</div>
         </div>'''

    cards = []
    for item in backlog_items:
        priority = str(item.get("priority", "INFO")).upper()
        title = str(item.get("title", "Untitled"))
        desc = str(item.get("description", ""))
        category = str(item.get("category", "FEATURE"))
        time_str = str(item.get("created_at", "")).replace("T", " ")[:16]
        
        # Check if there's a mission prompt embedded in the description
        prompt_html = ""
        if "**Mission Prompt:**" in desc:
            parts = desc.split("**Mission Prompt:**")
            desc_text = parts[0].strip()
            prompt_text = parts[1].strip()
            prompt_html = f'''
            <div class="cpo-prompt-box">
                <div class="cpo-prompt-title">&#x1F916; Antigravity Mission Prompt <span style="font-size:0.65rem;color:var(--muted);font-weight:normal;text-transform:none;">(Copy this to chat)</span></div>
                <div class="cpo-prompt-text">{prompt_text}</div>
            </div>'''
        else:
            desc_text = desc
            
        badge_color = "var(--blue)" if priority == "LOW" else "var(--yellow)" if priority == "MID" else "var(--red)" if priority == "HIGH" else "var(--muted)"

        html = f'''
        <div class="cpo-card {priority}">
            <div class="cpo-header">
                <div>
                    <div class="cpo-title">{title}</div>
                    <div class="cpo-meta" style="margin-top:6px">
                        <span class="badge" style="background:rgba(255,255,255,0.1);color:{badge_color}">{priority}</span>
                        <span class="badge" style="background:rgba(255,255,255,0.05);color:var(--muted)">{category}</span>
                    </div>
                </div>
                <div style="font-size:0.75rem;color:var(--muted)">{time_str}</div>
            </div>
            <div class="cpo-desc">{desc_text}</div>
            {prompt_html}
        </div>
        '''
        cards.append(html)

    return f'''
    <div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F4CB; System Backlog & Ideas</span>
            <span class="section-badge">{len(backlog_items)} insights</span>
            <span class="section-line"></span>
        </div>
        <div class="cpo-grid">
            {"".join(cards)}
        </div>
    </div>
    '''


def _build_monitor_section(agents):
    """Build the Health Monitor tab content from SwarmMonitor's Supabase record."""
    # Find SwarmMonitor agent record
    monitor_agent = next((a for a in agents if a.get("agent_name") == "SwarmMonitor"), None)

    if not monitor_agent:
        return '''
        <div class="explainer-card" style="border-color:var(--yellow)">
            <div class="explainer-title" style="color:var(--yellow)">&#x1F50D; Health Monitor — Starting Up</div>
            <div class="explainer-text">The SwarmMonitor watchdog is not yet reporting. It starts 60 seconds after the swarm boots and checks every 5 minutes.<br><br>If you just deployed, wait a moment and refresh.</div>
        </div>'''

    meta = monitor_agent.get("metadata") or {}
    issues = meta.get("issues", [])
    all_ok = meta.get("all_ok", len(issues) == 0)
    check_count = meta.get("check_count", 0)
    last_checked = meta.get("last_checked", monitor_agent.get("last_pulse", ""))
    interval_min = meta.get("check_interval_min", 5)

    # Format last checked time
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
        last_checked_fmt = dt.strftime("%H:%M:%S UTC")
    except Exception:
        last_checked_fmt = last_checked[:19] if last_checked else "N/A"

    # Count by severity
    if not isinstance(issues, list):
        issues = []
    high_count = sum(1 for i in issues if isinstance(i, dict) and i.get("severity") == "HIGH")
    med_count = sum(1 for i in issues if isinstance(i, dict) and i.get("severity") == "MEDIUM")
    low_count = sum(1 for i in issues if isinstance(i, dict) and i.get("severity") == "LOW")
    pipeline_issues = sum(1 for i in issues if isinstance(i, dict) and i.get("type") in ("NO_OUTPUT", "PIPELINE_BLOCKED", "STALE_OUTPUT"))

    # Human-readable issue type labels
    TYPE_LABELS = {
        "AGENT_MISSING": "🚫 Missing Agent",
        "AGENT_ERROR": "💥 Agent Error",
        "AGENT_STALE": "⏰ Stale Heartbeat",
        "CYCLE_FROZEN": "🧊 Frozen Cycles",
        "LOG_ERRORS": "📋 Log Errors",
        "DB_UNAVAILABLE": "🗄️ Database Down",
        "DB_ERROR": "🗄️ Database Error",
        "NO_OUTPUT": "📭 No Output",
        "PIPELINE_BLOCKED": "🚧 Pipeline Blocked",
        "STALE_OUTPUT": "📦 Stale Output",
    }

    # Overall status banner
    if all_ok:
        banner = f'''<div class="monitor-ok">
            <span class="big-check">&#x2705;</span>
            <div>
                <div>All agents healthy — no issues detected</div>
                <div style="font-size:.8rem;font-weight:400;color:var(--muted);margin-top:3px">Last checked: {last_checked_fmt} &bull; Check #{check_count} &bull; Every {interval_min} min</div>
            </div>
        </div>'''
    else:
        banner = f'''<div class="monitor-ok" style="background:rgba(239,68,68,0.1);border-color:rgba(239,68,68,0.3);color:var(--red)">
            <span class="big-check">&#x26A0;&#xFE0F;</span>
            <div>
                <div>{len(issues)} issue(s) detected &mdash; {high_count} high &bull; {med_count} medium &bull; {low_count} low</div>
                <div style="font-size:.8rem;font-weight:400;color:var(--muted);margin-top:3px">Last checked: {last_checked_fmt} &bull; Check #{check_count} &bull; Every {interval_min} min</div>
            </div>
        </div>'''

    # Stats bar
    total_agents = 5  # EXPECTED_AGENTS
    errored = sum(1 for i in issues if isinstance(i, dict) and i.get("type") in ("AGENT_ERROR", "AGENT_MISSING", "AGENT_STALE"))
    healthy = total_agents - errored
    stats_html = f'''<div class="monitor-meta">
        <div class="mstat"><div class="big" style="color:var(--green)">{healthy}</div><div class="lbl">Healthy Agents</div></div>
        <div class="mstat"><div class="big" style="color:{'var(--red)' if high_count else 'var(--muted)'}">{high_count}</div><div class="lbl">High Issues</div></div>
        <div class="mstat"><div class="big" style="color:{'var(--yellow)' if med_count else 'var(--muted)'}">{med_count}</div><div class="lbl">Medium Issues</div></div>
        <div class="mstat"><div class="big" style="color:{'var(--yellow)' if pipeline_issues else 'var(--muted)'}">{pipeline_issues}</div><div class="lbl">Pipeline Issues</div></div>
        <div class="mstat"><div class="big">{check_count}</div><div class="lbl">Total Checks</div></div>
    </div>'''

    # Issues table
    if not issues:
        table_html = '<div style="color:var(--muted);text-align:center;padding:40px;font-size:.9rem">&#x2705; No issues found in the last check</div>'
    else:
        rows = []
        for iss in issues:
            if not isinstance(iss, dict):
                continue
            sev = iss.get("severity", "LOW")
            itype = iss.get("type", "UNKNOWN")
            type_label = TYPE_LABELS.get(itype, itype)
            agent = iss.get("agent", "")
            msg = iss.get("message", "")
            detail = iss.get("detail", "")
            detected = iss.get("detected_at", "")
            pulse = iss.get("last_pulse", "")
            try:
                pulse_fmt = datetime.fromisoformat(pulse.replace("Z", "+00:00")).strftime("%H:%M:%S") if pulse else "—"
            except Exception:
                pulse_fmt = pulse[:19] if pulse else "—"

            detail_html = f'<div class="issue-detail">{detail[:400]}</div>' if detail else ""
            detected_html = f'<div style="color:var(--muted);font-size:0.75rem;margin-top:4px">&#x23F2;&#xFE0F; Detected: {detected}</div>' if detected else ""
            
            rows.append(f'''<tr>
                <td><span class="sev-badge {sev}">{sev}</span></td>
                <td style="color:var(--cyan);white-space:nowrap">{type_label}</td>
                <td style="font-weight:600">{agent}</td>
                <td>{msg}{detected_html}{detail_html}</td>
                <td style="color:var(--muted);font-size:.75rem;white-space:nowrap">{pulse_fmt}</td>
            </tr>''')

        table_html = f'''<div class="card" style="padding:0;overflow:hidden">
            <table class="issues-table">
                <thead><tr>
                    <th>Severity</th>
                    <th>Issue Type</th>
                    <th>Agent</th>
                    <th>Details</th>
                    <th>Last Pulse</th>
                </tr></thead>
                <tbody>{"".join(rows)}</tbody>
            </table>
        </div>'''

    return f'''<div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F50D; Swarm Health Monitor</span>
            <span class="section-badge">{len(issues)} active issues</span>
            <span class="section-line"></span>
        </div>
        {banner}
        {stats_html}
        <div class="section-header" style="margin-top:16px">
            <span class="section-title">Issue Log</span>
            <span class="section-line"></span>
        </div>
        {table_html}
    </div>'''


def _build_health_banner(agents):
    """Build a compact health strip for the top of the Pulse tab."""
    try:
        monitor = next((a for a in agents if isinstance(a, dict) and a.get("agent_name") == "SwarmMonitor"), None)
        if not monitor:
            return '<div class="health-strip boot" onclick="showTab(\'monitor\')">&#x23F3; Health Monitor starting up... click to check</div>'
        meta = monitor.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        issues = meta.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        all_ok = meta.get("all_ok", len(issues) == 0)
        if all_ok:
            return '<div class="health-strip ok" onclick="showTab(\'monitor\')">&#x2705; All systems healthy &mdash; all agents running normally</div>'
        high = sum(1 for i in issues if isinstance(i, dict) and i.get("severity") == "HIGH")
        return f'<div class="health-strip warn" onclick="showTab(\'monitor\')">&#x26A0;&#xFE0F; {len(issues)} issue(s) detected ({high} critical) &mdash; click for details</div>'
    except Exception:
        return '<div class="health-strip boot" onclick="showTab(\'monitor\')">&#x23F3; Health Monitor loading...</div>'


def _build_scout_summary(agents):
    """Build a compact scout stats strip for the Pulse tab."""
    try:
        scout = next((a for a in agents if isinstance(a, dict) and a.get("agent_name") in ("Scout", "ResearchAgent")), None)
        if not scout:
            return ""
        meta = scout.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        scanned = meta.get("tickers_scanned", meta.get("universe_size", 0))
        approved = meta.get("approved_count", meta.get("proposals_count", 0))
        # Fallback: try scan_results
        sr = meta.get("scan_results", {})
        if not isinstance(sr, dict):
            sr = {}
        if not scanned and sr:
            scanned = sr.get("total_scanned", 0)
            approved = sr.get("approved", 0)
        cycle = scout.get("cycle_count", 0)
        if not scanned:
            return f'<div class="scout-strip">&#x1F52C; <span style="color:var(--cyan);font-weight:600">Scout</span> <span style="color:var(--muted)">Cycle {cycle} &bull; Scanning market...</span></div>'
        return f'''<div class="scout-strip" onclick="showTab('scout')" style="cursor:pointer">
            &#x1F52C; <span style="color:var(--cyan);font-weight:600">Scout</span>
            <span><strong>{scanned}</strong> assets scanned</span>
            <span>&#x2192;</span>
            <span style="color:var(--green);font-weight:600">{approved} approved</span>
            <span style="color:var(--muted);margin-left:auto">Cycle #{cycle} &bull; click for details</span>
        </div>'''
    except Exception:
        return ""


def _describe_decision(decision, score, reason, next_step):
    """Turn a technical decision into plain English."""
    dec = str(decision).upper()
    s = float(score) if score else 0

    # Verdict in plain language
    if dec in ("BUY", "LONG"):
        verdict_text = "Buy opportunity — our analysts see upward potential"
    elif dec in ("SELL", "SHORT"):
        verdict_text = "Sell opportunity — our analysts expect a decline"
    elif dec == "MONITOR":
        verdict_text = "Worth watching — mixed signals, not ready yet"
    elif dec in ("NO_GO", "SKIP"):
        verdict_text = "Pass — the signals aren't strong enough right now"
    elif dec == "PENDING":
        verdict_text = "Still being analyzed..."
    else:
        verdict_text = f"Decision: {dec}"

    # Next step in plain language
    ns = str(next_step).upper()
    if "EXECUTE" in ns or "BUY" in ns or "LONG" in ns:
        next_text = "Ready to trade — moving to execution"
    elif "RISK" in ns:
        next_text = "Checking risk limits before trading"
    elif "MONITOR" in ns or "WATCH" in ns:
        next_text = "Added to watchlist — waiting for better entry price"
    elif "REJECT" in ns or "NO_GO" in ns or "SKIP" in ns:
        next_text = "Not proceeding — signals too weak"
    elif "PENDING" in ns:
        next_text = "Waiting to be analyzed..."
    else:
        next_text = next_step

    return verdict_text, next_text


def _build_history_matrix_section():
    """Builds the 12-Hour Decision History table from the footprint file."""
    import os, json
    from datetime import datetime, timedelta
    
    history_file = "decision_history.json"
    if not os.path.exists(history_file):
        return ""
        
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            raw = f.read()
        try:
            history_data = json.loads(raw)
        except json.JSONDecodeError:
            # File corrupted — try to salvage by truncating to last valid array
            last_bracket = raw.rfind(']')
            if last_bracket > 0:
                try:
                    history_data = json.loads(raw[:last_bracket + 1])
                except json.JSONDecodeError:
                    return '<div style="color:var(--muted)">Decision history file is corrupted. It will self-heal on next cycle.</div>'
            else:
                return ""

        if not history_data:
            return ""
            
        cutoff = datetime.now() - timedelta(hours=12)
        
        recent_decisions = []
        for d in history_data:
            ts_str = d.get('timestamp', '')
            try:
                # Remove Z or timezone for naive comparison
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")[:19])
                if dt >= cutoff:
                    recent_decisions.append((dt, d))
            except Exception:
                pass
                
        if not recent_decisions:
            return '<div style="margin-top:20px;color:var(--muted)">No trading decisions recorded in the last 12 hours.</div>'
            
        # Sort descending by time
        recent_decisions.sort(key=lambda x: x[0], reverse=True)
        
        rows = []
        for dt, d in recent_decisions:
            decision = d.get("decision", "UNKNOWN")
            # --- PIVOT: Filter out NO_GO entirely from Near-Miss Matrix ---
            if decision in ('NO_GO', 'SKIP', 'PENDING'):
                continue
                
            time_fmt = dt.strftime("%H:%M:%S")
            ticker = d.get("ticker", "?")
            score = d.get("score", 0)
            reason = d.get("reason", "")
            
            direction = d.get("direction", "LONG")
            target = d.get("target_entry_price", 0.0)
            current = d.get("current_price", 0.0)
            sl_pct = d.get("stop_loss_pct", 5.0)
            rrr = d.get("rrr", "1:1.5")
            
            # Calculate distance to entry Koers
            dist_pct = 0.0
            dist_color = "var(--text)"
            if current > 0 and target > 0:
                dist_pct = abs(current - target) / current * 100.0
                if dist_pct < 1.0:
                    dist_color = "var(--green)" # Super close to entry
                elif dist_pct < 3.0:
                    dist_color = "var(--yellow)" # Getting warm
            
            setup_str = f"<span style='color:var(--text)'>Trgt: ${target:.4f}</span><br><span style='color:var(--muted);font-size:0.7rem'>SL: {sl_pct}% | RRR {rrr}</span>"
            dist_str = f"<span style='color:{dist_color};font-weight:600'>{dist_pct:.2f}%</span><br><span style='color:var(--muted);font-size:0.65rem'>Current: ${current:.4f}</span>"
            
            if decision == 'BUILD_CASE': 
                emoji = '🟢'
                dec_class = "APPROVED"
                color = "var(--green)"
            elif decision == 'MONITOR': 
                emoji = '🟡'
                dec_class = "MONITORED"
                color = "var(--cyan)"
            else:
                emoji = '⚪'
                dec_class = "SKIPPED"
                color = "var(--cyan)"
                
            dir_color = "var(--green)" if direction == "LONG" else "var(--red)"
            score_formatted = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
                
            rows.append(f'''
            <tr style="border-left:3px solid {color}">
                <td>{time_fmt}</td>
                <td style="font-weight:600;color:var(--cyan)">{ticker}<br><span style="font-size:0.65rem;color:{dir_color};border:1px solid {dir_color};padding:1px 4px;border-radius:4px">{direction}</span></td>
                <td><span class="status-pill {dec_class}">{emoji} {decision}</span><br><span style="color:var(--text);font-weight:600;font-size:0.8rem">{score_formatted}</span></td>
                <td style="line-height:1.4">{setup_str}</td>
                <td style="line-height:1.4">{dist_str}</td>
                <td style="color:var(--muted);font-size:0.8rem;line-height:1.4">{reason}</td>
            </tr>
            ''')
            
        if not rows:
            return '<div style="margin-top:20px;color:var(--muted)">No near-miss trade setups recorded in the last 12 hours. Waiting for Scout to find viable candidates.</div>'
            
        return f'''
        <div class="section" style="margin-top:32px;">
            <div class="section-header">
                <span class="section-title">&#x1F552; 12-Hour Near-Miss Trade Setups</span>
                <span class="section-badge">{len(rows)} setups identified</span>
                <span class="section-line"></span>
            </div>
            <div class="card" style="padding:0;overflow:hidden">
                <table class="scan-table">
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Asset</th>
                            <th>Status & Score</th>
                            <th>Trade Setup</th>
                            <th>Dist. to Entry</th>
                            <th>Rationale</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(rows)}
                    </tbody>
                </table>
            </div>
        </div>
        '''
    except Exception as e:
        logger.error(f"Error building history matrix CSS: {e}")
        return f'<div class="error-msg">Error loading history matrix: {e}</div>'


def _build_decisions_section(project_lead_decisions):
    """Build the Decisions tab with layman-language cards and compacted NO_GOs."""
    if not project_lead_decisions:
        return '''<div class="explainer-card" style="border-color:var(--muted)">
            <div class="explainer-title" style="color:var(--muted)">&#x1F4CB; No decisions yet</div>
            <div class="explainer-text">The system is still analyzing market opportunities. Decisions will appear here after the first analysis cycle completes.</div>
        </div>'''

    active_cards = []
    skipped_tickers = []
    
    buy_count = 0
    skip_count = 0
    monitor_count = 0

    for d in project_lead_decisions:
        try:
            ticker = d.get('ticker', '?') if isinstance(d, dict) else str(d)
            timeframe = d.get('timeframe', '1h') if isinstance(d, dict) else '1h'
            if not isinstance(d, dict):
                active_cards.append(f'<div class="decision-card"><div class="dec-ticker">{ticker}</div><div class="dec-reason">Data pending...</div></div>')
                continue
                
            decision = str(d.get('decision', 'PENDING')).upper()
            score = d.get('score', 0)
            reason = d.get('reason', '')
            bull_case = d.get('bull_case', '')
            bear_case = d.get('bear_case', '')
            next_step = d.get('next_step', 'PENDING')
            ts = d.get('time', '')
            
            # Extract new metrics
            analysis = d.get('analysis', {}) if 'analysis' in d else d # Check if nested or flat
            target_price = d.get('target_entry_price', 0.0) # Assume flat for pipeline decisions array
            monitoring_rationale = d.get('monitoring_rationale', '')
            trend_timeframe = d.get('trend_timeframe', '')

            if decision in ('BUY', 'LONG'): buy_count += 1
            elif decision == 'MONITOR': monitor_count += 1
            elif decision in ('NO_GO', 'SKIP'): skip_count += 1

            # Compact NO_GOs and PENDINGs
            if decision in ('NO_GO', 'SKIP'):
                skipped_tickers.append(f'<span class="status-pill REJECTED" style="margin:2px;" title="{reason}">{ticker} ({timeframe}) ({score:.2f})</span>')
                continue
            if decision == 'PENDING':
                skipped_tickers.append(f'<span class="status-pill MONITORED" style="margin:2px;" title="Queued for analysis">{ticker} ({timeframe}) (pending)</span>')
                continue

            verdict_text, next_text = _describe_decision(decision, score, reason, next_step)

            # Build Metrics for MONITOR
            metrics_html = ""
            if decision == 'MONITOR' and target_price:
                 metrics_html = f'''
                 <div style="display:flex; gap:12px; margin-top:12px; margin-bottom:12px; padding:10px; background:rgba(245,158,11,0.06); border:1px dashed rgba(245,158,11,0.3); border-radius:8px;">
                     <div><div style="font-size:0.65rem;color:var(--muted);text-transform:uppercase;">Entry Target Price</div><div style="font-size:0.9rem;font-weight:700;color:var(--yellow);">${target_price:.6f}</div></div>
                     <div><div style="font-size:0.65rem;color:var(--muted);text-transform:uppercase;">Trend Scale</div><div style="font-size:0.9rem;font-weight:700;color:var(--text);">{trend_timeframe}</div></div>
                     <div style="flex:1;"><div style="font-size:0.65rem;color:var(--muted);text-transform:uppercase;">Rationale</div><div style="font-size:0.75rem;color:var(--text);">{monitoring_rationale}</div></div>
                 </div>'''

            # Bull/bear in plain language
            bull_html = ""
            bear_html = ""
            if bull_case and bull_case != "N/A" and bull_case != "...":
                bull_html = f'<div class="dec-case bull"><strong style="color:var(--green)">&#x1F4C8; Why it could go up</strong>{bull_case}</div>'
            if bear_case and bear_case != "N/A" and bear_case != "...":
                bear_html = f'<div class="dec-case bear"><strong style="color:var(--red)">&#x1F4C9; Why it could go down</strong>{bear_case}</div>'

            cases_html = ""
            if bull_html or bear_html:
                cases_html = f'<div class="dec-cases">{bull_html}{bear_html}</div>'

            card = f'''<div class="decision-card {decision}">
                <div class="dec-header">
                    <span class="dec-ticker">{ticker} <span style="font-size:0.65rem;color:var(--muted)">({timeframe})</span></span>
                    <span class="dec-verdict {decision}">{decision}</span>
                </div>
                <div class="dec-reason">{verdict_text}</div>
                {metrics_html}
                {cases_html}
                <div class="dec-next">&#x23E9; Next: {next_text}</div>
                <div style="margin-top:8px;font-size:.7rem;color:var(--muted)">Analyzed at {ts}</div>
            </div>'''
            active_cards.append(card)
        except Exception as e:
            active_cards.append(f'<div class="decision-card"><div class="dec-reason" style="color:var(--muted)">Error rendering: {e}</div></div>')

    summary = f'''<div style="display:flex;gap:16px;margin-bottom:20px;font-size:.9rem">
        <span style="color:var(--green);font-weight:600">&#x2705; {buy_count} Buy</span>
        <span style="color:var(--yellow);font-weight:600">&#x1F440; {monitor_count} Watching</span>
        <span style="color:var(--muted);font-weight:600">&#x274C; {skip_count} Passed</span>
        <span style="color:var(--muted);margin-left:auto">{len(project_lead_decisions)} assets analyzed this cycle</span>
    </div>'''
    
    skipped_html = ""
    if skipped_tickers:
         skipped_html = f'''
         <div class="section-header" style="margin-top:24px;">
             <span class="section-title">Skipped Assets (No Go)</span>
         </div>
         <div style="padding:12px; background:rgba(255,255,255,0.02); border-radius:8px; border:1px solid var(--border);">
             {"".join(skipped_tickers)}
         </div>'''

    return f'''<div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F4CB; Latest Decisions</span>
            <span class="section-badge">{len(project_lead_decisions)} assets analyzed</span>
            <span class="section-line"></span>
        </div>
        {summary}
        {"".join(active_cards)}
        {skipped_html}
    </div>
    {_build_history_matrix_section()}'''


def _build_opportunities_section(open_opportunities):
    """Build enriched opportunities section with near-miss-style data."""
    if not open_opportunities:
        return ""

    # Filter out USDT tickers when USDC variant exists
    usdc_tickers = {o.get("ticker", "") for o in open_opportunities if "USDC" in o.get("ticker", "")}
    clean_opps = []
    for o in open_opportunities:
        t = o.get("ticker", "")
        if "USDT" in t:
            usdc_variant = t.replace("USDT", "USDC")
            if usdc_variant in usdc_tickers:
                continue  # Skip USDT when USDC exists
        clean_opps.append(o)
    
    if not clean_opps:
        return ""

    cards = []
    for opp in clean_opps:
        ticker = opp.get('ticker', 'UNKNOWN')
        timeframe = opp.get('timeframe', '1h')
        score = opp.get('current_score', 0)
        duration = opp.get('duration_hours', 0)
        reason = opp.get('latest_reason', 'Monitoring')
        next_step = opp.get('next_step', 'PENDING')
        direction = opp.get('direction', 'LONG')
        target = opp.get('target_entry_price', 0.0)
        current = opp.get('current_price', 0.0)
        rationale = opp.get('monitoring_rationale', '')
        rrr = opp.get('rrr', '1:1.5')
        sl_pct = opp.get('stop_loss_pct', 5.0)
        last_updated = opp.get('last_updated', '')
        price_history = opp.get('price_history', [])

        # Trade probability from score
        prob = max(0, min(100, int(abs(score) * 100)))
        if prob >= 70:
            bar_color = "var(--green)"
        elif prob >= 40:
            bar_color = "var(--yellow)"
        else:
            bar_color = "var(--red)"

        # Direction badge
        dir_color = "var(--green)" if direction == "LONG" else "var(--red)"
        dir_label = direction.upper()

        # Distance to entry
        dist_html = ""
        if current > 0 and target > 0:
            dist_pct = abs(current - target) / current * 100.0
            if dist_pct < 1.0:
                dist_color = "var(--green)"
            elif dist_pct < 3.0:
                dist_color = "var(--yellow)"
            else:
                dist_color = "var(--text)"
            dist_html = f'''<div style="text-align:right">
                <div style="font-size:0.65rem;color:var(--muted);text-transform:uppercase">Dist to Entry</div>
                <div style="font-size:1rem;font-weight:700;color:{dist_color}">{dist_pct:.2f}%</div>
            </div>'''

        # Momentum arrow from price history
        momentum_html = ""
        if len(price_history) >= 2:
            trend = price_history[-1] - price_history[0]
            # For SHORTs: price going UP toward target is good
            # For LONGs: price going UP toward target is good (if target > current)
            if direction == "SHORT":
                moving_right = trend > 0  # Price rising toward short entry
            else:
                moving_right = trend > 0 if target > current else trend < 0
            
            if moving_right:
                arrow = "&#x2197;"  # ↗
                m_color = "var(--green)"
                m_text = "Moving toward entry"
            else:
                arrow = "&#x2198;"  # ↘
                m_color = "var(--yellow)"
                m_text = "Moving away from entry"
            momentum_html = f'<span style="color:{m_color};font-size:.8rem;font-weight:600" title="{m_text}">{arrow} {m_text}</span>'

        # Last updated
        last_check = ""
        if last_updated:
            try:
                last_check = last_updated.replace("T", " ")[:16]
            except:
                last_check = str(last_updated)[:16]

        # Duration label
        if duration < 1:
            dur_text = "Just spotted"
        elif duration < 24:
            dur_text = f"Watching for {duration:.0f}h"
        else:
            dur_text = f"Watching for {duration/24:.1f} days"

        # Setup info row
        setup_html = ""
        if target > 0:
            setup_html = f'''<div style="display:flex;gap:16px;align-items:center;margin:10px 0;padding:10px;background:rgba(245,158,11,0.06);border:1px dashed rgba(245,158,11,0.3);border-radius:8px;flex-wrap:wrap">
                <div><div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase">Target Entry</div><div style="font-size:0.95rem;font-weight:700;color:var(--yellow)">${target:.4f}</div></div>
                <div><div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase">Current</div><div style="font-size:0.95rem;font-weight:600;color:var(--text)">${current:.4f}</div></div>
                <div><div style="font-size:0.6rem;color:var(--muted);text-transform:uppercase">Setup</div><div style="font-size:0.85rem;color:var(--text)">SL: {sl_pct}% | RRR {rrr}</div></div>
                <div style="flex:1;text-align:right">{momentum_html}</div>
            </div>'''

        # Rationale (plain English)
        rationale_html = ""
        if rationale and rationale not in ("N/A", ""):
            rationale_html = f'<div style="font-size:.8rem;color:var(--muted);margin-bottom:8px;font-style:italic">&#x1F4AC; {rationale}</div>'

        card = f'''<div class="opp-card">
            <div class="opp-header">
                <span class="opp-ticker">{ticker} <span style="font-size:0.65rem;color:var(--muted)">({timeframe})</span> <span style="font-size:0.65rem;color:{dir_color};border:1px solid {dir_color};padding:1px 6px;border-radius:4px;margin-left:6px">{dir_label}</span></span>
                <div style="text-align:right">
                    <span class="opp-time">{dur_text}</span>
                    <div style="font-size:.65rem;color:var(--muted)">{last_check}</div>
                </div>
            </div>
            {setup_html}
            {rationale_html}
            <div style="display:flex;justify-content:space-between;align-items:flex-end;margin-top:8px">
                <div style="flex:1;margin-right:16px">
                    <div class="prob-label"><span>Trade likelihood</span><span style="font-weight:600;color:{bar_color}">{prob}%</span></div>
                    <div class="prob-bar"><div class="prob-fill" style="width:{prob}%;background:{bar_color}"></div></div>
                </div>
                {dist_html}
            </div>
        </div>'''
        cards.append(card)

    return f'''<div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F5D3; Open Opportunities</span>
            <span class="section-badge">{len(clean_opps)} being watched</span>
            <span class="section-line"></span>
        </div>
        {"".join(cards)}
    </div>'''


def _build_activity_feed_tab():
    """Build the Activity Feed tab: pipeline event timeline + ticker journeys."""
    import os, json
    from datetime import datetime, timedelta

    try:
        from utils.pipeline_events import get_events
    except ImportError:
        return '<div style="color:var(--muted)">Pipeline events module not available.</div>'

    events = get_events(limit=200)
    if not events:
        return '''<div class="explainer-card">
            <div class="explainer-title">&#x1F4E1; Activity Feed</div>
            <div class="explainer-text">No pipeline events recorded yet. Events will appear after the first analysis cycle completes.</div>
        </div>'''

    # --- Section A: Pipeline Flow Summary (last 1h) ---
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    recent = []
    for e in events:
        try:
            ts = datetime.fromisoformat(e["timestamp"][:19])
            if ts >= one_hour_ago:
                recent.append(e)
        except Exception:
            pass

    type_counts = {}
    for e in recent:
        t = e.get("event_type", "UNKNOWN")
        type_counts[t] = type_counts.get(t, 0) + 1

    decisions = type_counts.get("DECISION", 0)
    narrators = type_counts.get("NARRATOR_CHECK", 0)
    risks = type_counts.get("RISK_CHECK", 0)
    executions = type_counts.get("EXECUTION", 0)
    exits = type_counts.get("TRADE_EXIT", 0)
    expired = type_counts.get("MONITOR_EXPIRED", 0)

    summary_html = f'''<div class="af-summary">
        <div class="af-stat"><div class="big" style="color:var(--blue)">{decisions}</div><div class="lbl">Decisions</div></div>
        <div class="af-stat"><div class="big" style="color:var(--purple)">{narrators}</div><div class="lbl">Narrator</div></div>
        <div class="af-stat"><div class="big" style="color:var(--cyan)">{risks}</div><div class="lbl">Risk Checks</div></div>
        <div class="af-stat"><div class="big" style="color:var(--green)">{executions}</div><div class="lbl">Executions</div></div>
        <div class="af-stat"><div class="big" style="color:var(--yellow)">{exits}</div><div class="lbl">Exits</div></div>
        <div class="af-stat"><div class="big" style="color:var(--red)">{expired}</div><div class="lbl">Expired</div></div>
    </div>'''

    # --- Section B: Event Timeline (reverse-chronological) ---
    timeline_cards = []
    for e in events[:50]:  # Show last 50 events
        event_type = e.get("event_type", "UNKNOWN")
        ticker = e.get("ticker", "?")
        data = e.get("data", {})
        ts_raw = e.get("timestamp", "")

        try:
            ts_dt = datetime.fromisoformat(ts_raw[:19])
            ts_fmt = ts_dt.strftime("%H:%M:%S")
        except Exception:
            ts_fmt = ts_raw[:19]

        # Build one-line summary
        summary = _format_event_summary(event_type, ticker, data)

        # Build expandable details
        detail_lines = []
        for k, v in data.items():
            detail_lines.append(f"{k}: {v}")
        details_str = "\n".join(detail_lines) if detail_lines else "No additional data"

        card = f'''<div class="af-event {event_type}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                <div><span class="af-badge {event_type}">{event_type.replace("_", " ")}</span> <strong style="margin-left:8px">{ticker}</strong></div>
                <span class="af-time">{ts_fmt}</span>
            </div>
            <div class="af-summary-line">{summary}</div>
            <details><summary style="font-size:.7rem;color:var(--muted);cursor:pointer;margin-top:4px">Details</summary>
                <div class="af-details">{details_str}</div>
            </details>
        </div>'''
        timeline_cards.append(card)

    timeline_html = "\n".join(timeline_cards)

    # --- Section C: Ticker Journey Tracker ---
    ticker_events = {}
    for e in events:
        t = e.get("ticker", "?")
        if t not in ticker_events:
            ticker_events[t] = []
        ticker_events[t].append(e)

    journey_cards = []
    # Sort tickers by most recent event
    sorted_tickers = sorted(ticker_events.keys(),
                            key=lambda t: ticker_events[t][-1].get("timestamp", ""),
                            reverse=True)

    for ticker in sorted_tickers[:20]:  # Top 20 tickers
        t_events = ticker_events[ticker]
        # Chronological order for journey
        dots_html = ""
        journey_lines = []
        for e in t_events[-15:]:  # Last 15 events per ticker
            et = e.get("event_type", "UNKNOWN")
            data = e.get("data", {})
            ts_raw = e.get("timestamp", "")
            try:
                ts_fmt = datetime.fromisoformat(ts_raw[:19]).strftime("%H:%M")
            except Exception:
                ts_fmt = "?"
            dots_html += f'<span class="af-dot {et}" title="{et} @ {ts_fmt}"></span>'
            summary = _format_event_summary(et, ticker, data)
            journey_lines.append(f'<div style="padding:4px 0;font-size:.8rem;border-bottom:1px solid rgba(255,255,255,0.04)"><span class="af-badge {et}" style="font-size:.6rem">{et.replace("_"," ")}</span> <span class="af-time">{ts_fmt}</span> &mdash; {summary}</div>')

        last_state = ""
        for e in reversed(t_events):
            if e.get("event_type") == "DECISION":
                last_state = e.get("data", {}).get("to_state", "")
                break

        state_badge = f' <span class="af-badge DECISION" style="margin-left:8px">{last_state}</span>' if last_state else ""

        card = f'''<details class="af-journey">
            <summary>{ticker}{state_badge} <span style="font-size:.75rem;color:var(--muted);margin-left:12px">{len(t_events)} events</span>
                <div style="margin-top:6px">{dots_html}</div>
            </summary>
            <div style="margin-top:12px">{"".join(journey_lines)}</div>
        </details>'''
        journey_cards.append(card)

    journey_html = "\n".join(journey_cards)

    return f'''
    <div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F4E1; Pipeline Activity (Last 1h)</span>
            <span class="section-badge">{len(recent)} events</span>
            <span class="section-line"></span>
        </div>
        {summary_html}
    </div>

    <div class="section">
        <div class="section-header">
            <span class="section-title">&#x23F3; Event Timeline</span>
            <span class="section-badge">Last {len(timeline_cards)} events</span>
            <span class="section-line"></span>
        </div>
        {timeline_html}
    </div>

    <div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F4CD; Ticker Journeys</span>
            <span class="section-badge">{len(journey_cards)} tickers</span>
            <span class="section-line"></span>
        </div>
        {journey_html}
    </div>'''


def _format_event_summary(event_type: str, ticker: str, data: dict) -> str:
    """Generate a human-readable one-line summary for a pipeline event."""
    if event_type == "DECISION":
        from_s = data.get("from_state", "?")
        to_s = data.get("to_state", "?")
        score = data.get("score", 0)
        return f"{from_s} &#x2192; {to_s} (score: {score})"
    elif event_type == "NARRATOR_CHECK":
        status = data.get("status", "?")
        color = "var(--green)" if status == "VALID" else "var(--red)"
        return f'Narrative: <span style="color:{color};font-weight:600">{status}</span>'
    elif event_type == "RISK_CHECK":
        approved = data.get("approved", False)
        label = "APPROVED" if approved else "REJECTED"
        color = "var(--green)" if approved else "var(--red)"
        kelly = data.get("kelly_fraction", 0)
        return f'Risk: <span style="color:{color};font-weight:600">{label}</span> (Kelly: {kelly})'
    elif event_type == "EXECUTION":
        action = data.get("action", "?")
        value = data.get("trade_value", 0)
        status = data.get("status", "?")
        return f'{action} ${value:.0f} &mdash; {status}'
    elif event_type == "TRADE_EXIT":
        reason = data.get("exit_reason", "?")
        pnl = data.get("pnl", 0)
        color = "var(--green)" if pnl >= 0 else "var(--red)"
        return f'Closed ({reason}) &mdash; PnL: <span style="color:{color};font-weight:600">${pnl:.2f}</span>'
    elif event_type == "MONITOR_EXPIRED":
        reason = data.get("reason", "Unknown")
        return f'Removed from watchlist: {reason}'
    else:
        return str(data)[:100]


def _build_ticker_matrix_tab():
    """Build a Ticker Matrix tab: color-coded grid of all tickers with latest analysis state."""
    import os, json
    from datetime import datetime, timedelta
    
    history_file = "decision_history.json"
    if not os.path.exists(history_file):
        return '''<div class="explainer-card">
            <div class="explainer-title">&#x1F4CA; Ticker Matrix</div>
            <div class="explainer-text">No analysis data available yet. The matrix will populate after the first analysis cycle completes.</div>
        </div>'''
    
    try:
        with open(history_file, 'r') as f:
            history_data = json.load(f)
    except Exception:
        return '<div style="color:var(--muted)">Error loading decision history.</div>'
    
    if not history_data:
        return '<div style="color:var(--muted)">No analysis history found.</div>'
    
    # Group by setup_id (ticker + timeframe), keep only latest decision per setup
    setup_latest = {}
    for d in history_data:
        setup_id = d.get("setup_id", d.get("ticker", ""))
        ticker = d.get("ticker", "")
        if not setup_id:
            continue
        ts_str = d.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")[:19])
        except Exception:
            dt = datetime.min
        
        if setup_id not in setup_latest or dt > setup_latest[setup_id]["_dt"]:
            d["_dt"] = dt
            setup_latest[setup_id] = d
    
    if not setup_latest:
        return '<div style="color:var(--muted)">No ticker data to display.</div>'
    
    # Sort by recency (most recent first)
    sorted_setups = sorted(setup_latest.values(), key=lambda x: x.get("_dt", datetime.min), reverse=True)
    
    # Decision color map
    color_map = {
        "BUILD_CASE": ("var(--green)", "&#x1F7E2;", "APPROVED"),
        "BUY": ("var(--green)", "&#x1F7E2;", "APPROVED"),
        "LONG": ("var(--green)", "&#x1F7E2;", "APPROVED"),
        "SELL": ("var(--green)", "&#x1F7E2;", "APPROVED"),
        "SHORT": ("var(--green)", "&#x1F7E2;", "APPROVED"),
        "MONITOR": ("var(--yellow)", "&#x1F7E1;", "MONITORED"),
        "NO_GO": ("var(--muted)", "&#x26D4;", "REJECTED"),
        "SKIP": ("var(--muted)", "&#x26D4;", "REJECTED"),
        "PENDING": ("var(--cyan)", "&#x23F3;", "MONITORED"),
    }
    
    cards_html = []
    for d in sorted_setups:
        ticker = d.get("ticker", "?")
        timeframe = d.get("timeframe", "1h")
        decision = d.get("decision", "UNKNOWN")
        score = d.get("score", 0)
        direction = d.get("direction", "LONG")
        target = d.get("target_entry_price", 0.0)
        current = d.get("current_price", 0.0)
        dt = d.get("_dt", datetime.min)
        
        color, emoji, pill_class = color_map.get(decision, ("var(--muted)", "&#x2B1C;", "SKIPPED"))
        dir_color = "var(--green)" if direction == "LONG" else "var(--red)"
        
        # Time ago
        try:
            diff = datetime.now() - dt
            if diff.total_seconds() < 3600:
                time_ago = f"{int(diff.total_seconds() / 60)}m ago"
            elif diff.total_seconds() < 86400:
                time_ago = f"{int(diff.total_seconds() / 3600)}h ago"
            else:
                time_ago = f"{int(diff.total_seconds() / 86400)}d ago"
        except:
            time_ago = "?"
        
        last_check = dt.strftime("%H:%M:%S") if dt != datetime.min else "?"
        
        # Dist to entry
        dist_str = ""
        target_str = ""
        if decision not in ("NO_GO", "SKIP"):
            if current > 0 and target > 0:
                dist_pct = abs(current - target) / current * 100.0
                if dist_pct < 1.0:
                    dc = "var(--green)"
                elif dist_pct < 3.0:
                    dc = "var(--yellow)"
                else:
                    dc = "var(--text)"
                dist_str = f'<div style="font-size:.7rem;color:{dc};font-weight:600">Dist: {dist_pct:.1f}%</div>'
            
            if target > 0:
                target_str = f'<div style="font-size:.7rem;color:var(--muted)">Trgt: ${target:.4f}</div>'
        
        card = f'''<div style="background:var(--card);border:1px solid var(--border);border-left:4px solid {color};border-radius:10px;padding:12px;min-width:180px;display:flex;flex-direction:column;gap:4px">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-weight:700;color:var(--cyan);font-size:.9rem">{ticker} <span style="font-size:0.65rem;color:var(--muted)">({timeframe})</span></span>
                <span style="font-size:0.6rem;color:{dir_color};border:1px solid {dir_color};padding:1px 4px;border-radius:4px">{direction}</span>
            </div>
            <div style="display:flex;align-items:center;gap:6px;margin-top:2px">
                <span class="status-pill {pill_class}" style="font-size:.6rem">{emoji} {decision}</span>
                <span style="font-size:.75rem;font-weight:600;color:var(--text)">{score:.2f}</span>
            </div>
            {target_str}
            {dist_str}
            <div style="font-size:.6rem;color:var(--muted);margin-top:auto;padding-top:4px;border-top:1px solid var(--border)">{last_check} ({time_ago})</div>
        </div>'''
        cards_html.append(card)
    
    # Summary counts
    decision_counts = {}
    for d in sorted_setups:
        dec = d.get("decision", "UNKNOWN")
        decision_counts[dec] = decision_counts.get(dec, 0) + 1
    
    status_tooltips = {
        "BUILD_CASE": "Closest to a trade! Macro &amp; micro thesis both strong. Still passes through Narrator → Risk Manager → Execution. Re-checks every 5 min.",
        "MONITOR": "Bullish thesis valid but waiting for a specific entry price or setup to trigger. Re-checks every 10 min.",
        "NO_GO": "Rejected — score too low or conflicting signals. Cooldown 30 min before re-analysis.",
        "ERROR": "Analysis failed due to an API or data issue. Will retry next cycle.",
        "PENDING": "Fresh ticker, not yet analyzed. Will be processed on the next cycle.",
        "BUY": "Buy signal confirmed — execution pipeline triggered.",
        "LONG": "Long signal confirmed — execution pipeline triggered.",
        "SELL": "Sell signal confirmed — execution pipeline triggered.",
        "SHORT": "Short signal confirmed — execution pipeline triggered.",
        "SKIP": "Skipped — does not meet minimum criteria. Cooldown 30 min.",
    }

    summary_parts = []
    for dec, count in sorted(decision_counts.items()):
        color, emoji, _ = color_map.get(dec, ("var(--muted)", "", ""))
        tip = status_tooltips.get(dec, "")
        summary_parts.append(
            f'<span class="tip" style="color:{color};font-weight:600">{emoji} {count} {dec}<span class="tip-text">{tip}</span></span>'
        )
    
    legend_html = '''<details style="margin-bottom:16px;font-size:.75rem;color:var(--muted)">
            <summary style="cursor:pointer;color:var(--cyan);font-weight:600;font-size:.8rem;user-select:none">&#x2139;&#xFE0F; Status Legend &amp; Pipeline Flow</summary>
            <div style="margin-top:10px;padding:12px;background:rgba(0,0,0,0.3);border-radius:8px;border:1px solid var(--border)">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:10px;flex-wrap:wrap;font-size:.75rem;color:var(--text)">
                    <span style="padding:3px 8px;background:rgba(239,68,68,0.15);border-radius:4px;color:var(--red)">&#x26D4; NO_GO</span>
                    <span style="color:var(--muted)">&#x2192;</span>
                    <span style="padding:3px 8px;background:rgba(245,158,11,0.15);border-radius:4px;color:var(--yellow)">&#x1F7E1; MONITOR</span>
                    <span style="color:var(--muted)">&#x2192;</span>
                    <span style="padding:3px 8px;background:rgba(16,185,129,0.15);border-radius:4px;color:var(--green)">&#x1F7E2; BUILD_CASE</span>
                    <span style="color:var(--muted)">&#x2192;</span>
                    <span style="padding:3px 8px;background:rgba(59,130,246,0.15);border-radius:4px;color:var(--blue)">Narrator &#x2192; Risk &#x2192; Execute</span>
                </div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:8px;font-size:.7rem">
                    <div><span style="color:var(--red)">&#x26D4; NO_GO</span> &#x2014; Rejected. Cooldown 30 min.</div>
                    <div><span style="color:var(--yellow)">&#x1F7E1; MONITOR</span> &#x2014; Watching for entry price. Re-check 10 min.</div>
                    <div><span style="color:var(--green)">&#x1F7E2; BUILD_CASE</span> &#x2014; Closest to trade! Needs Narrator + Risk approval.</div>
                    <div><span style="color:var(--red)">&#x26A0; ERROR</span> &#x2014; Analysis failed. Retries next cycle.</div>
                </div>
            </div>
        </details>'''

    return f'''<div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F4CA; Ticker Analysis Matrix</span>
            <span class="section-badge">{len(sorted_setups)} tickers tracked</span>
            <span class="section-line"></span>
        </div>
        <div style="display:flex;gap:16px;margin-bottom:12px;font-size:.85rem;flex-wrap:wrap;align-items:center">
            {" &bull; ".join(summary_parts)}
        </div>
        {legend_html}
        <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(200px, 1fr));gap:12px">
            {"".join(cards_html)}
        </div>
    </div>'''


def _build_swarm_learner_section(learning_data):
    """Build the SwarmLearner Insights tab from learning_report.json data."""
    if not learning_data:
        return '''<div class="explainer-card" style="border-color:var(--purple)">
            <div class="explainer-title" style="color:var(--purple)">&#x1F52C; SwarmLearner Insights</div>
            <div class="explainer-text">SwarmLearner has not yet completed a cycle (runs every 20 cycles).</div>
        </div>'''

    # ── Extract fields ──
    timestamp = str(learning_data.get("timestamp", ""))[:19].replace("T", " ")
    total = learning_data.get("total_decisions", 0)
    funnel = learning_data.get("funnel", {})
    score_pass = funnel.get("score_pass", 0)
    build_case = funnel.get("build_case", 0)
    executed = funnel.get("executed", 0)
    near_miss = learning_data.get("near_miss_count", 0)
    bottleneck = str(learning_data.get("bottleneck_gate", "unknown")).lower()
    llm_summary = str(learning_data.get("llm_summary", "No diagnosis available."))
    indicator_scores = learning_data.get("indicator_scores", {})
    tech_avg = indicator_scores.get("tech", 0)
    fund_avg = indicator_scores.get("fund", 0)
    sent_avg = indicator_scores.get("sent", 0)
    score_dist = learning_data.get("score_distribution", {})
    threshold_impact = learning_data.get("threshold_impact", {})
    current_threshold = learning_data.get("current_threshold", 0.40)

    # Score pass / build_case rates
    score_pass_rate = f"{(score_pass / total * 100):.1f}%" if total else "N/A"
    build_case_rate = f"{(build_case / total * 100):.1f}%" if total else "N/A"

    # ── Bottleneck banner ──
    if bottleneck in ("execution", "execution_gate"):
        bn_color = "var(--red)"
        bn_bg = "rgba(239,68,68,0.12)"
        bn_border = "rgba(239,68,68,0.4)"
        bn_icon = "&#x1F6A8;"
        bn_label = "EXECUTION GATE"
    elif "llm" in bottleneck or "build_case" in bottleneck:
        bn_color = "var(--yellow)"
        bn_bg = "rgba(245,158,11,0.12)"
        bn_border = "rgba(245,158,11,0.4)"
        bn_icon = "&#x26A0;&#xFE0F;"
        bn_label = "LLM BUILD_CASE"
    elif "score" in bottleneck:
        bn_color = "var(--yellow)"
        bn_bg = "rgba(245,158,11,0.08)"
        bn_border = "rgba(245,158,11,0.3)"
        bn_icon = "&#x26A0;&#xFE0F;"
        bn_label = "SCORE THRESHOLD"
    else:
        bn_color = "var(--blue)"
        bn_bg = "rgba(59,130,246,0.08)"
        bn_border = "rgba(59,130,246,0.3)"
        bn_icon = "&#x1F50D;"
        bn_label = bottleneck.upper() or "UNKNOWN"

    bottleneck_html = f'''
    <div style="padding:16px 20px;background:{bn_bg};border:1px solid {bn_border};border-radius:12px;margin-bottom:20px;display:flex;align-items:center;gap:14px">
        <span style="font-size:1.8rem">{bn_icon}</span>
        <div>
            <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">Identified Bottleneck</div>
            <div style="font-size:1.3rem;font-weight:700;color:{bn_color}">{bn_label}</div>
        </div>
        <div style="margin-left:auto;font-size:.8rem;color:var(--muted)">Last updated: {timestamp or "N/A"} &bull; Every 20 cycles</div>
    </div>'''

    # ── Funnel metrics row ──
    exec_color = "var(--red)" if executed == 0 else "var(--green)"
    funnel_html = f'''
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px">
        <div class="mstat"><div class="big" style="color:var(--blue)">{score_pass_rate}</div><div class="lbl">Score Pass Rate (&ge;{current_threshold})</div></div>
        <div class="mstat"><div class="big" style="color:var(--purple)">{build_case_rate}</div><div class="lbl">BUILD_CASE Rate</div></div>
        <div class="mstat"><div class="big" style="color:var(--yellow)">{near_miss}</div><div class="lbl">Near-Miss (0.30–0.40)</div></div>
        <div class="mstat"><div class="big" style="color:{exec_color}">{executed}</div><div class="lbl">Executed Trades</div></div>
    </div>'''

    # ── Indicator scores ──
    scores = {"Tech": tech_avg, "Fund": fund_avg, "Sent": sent_avg}
    lowest_key = min(scores, key=scores.get)
    ind_cols = []
    for label, val in scores.items():
        color = "var(--red)" if label == lowest_key else "var(--green)"
        bar_w = min(int(val * 200), 100)
        ind_cols.append(f'''
        <div class="mstat">
            <div style="font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">{label} (avg)</div>
            <div style="font-size:1.6rem;font-weight:700;color:{color}">{val:.3f}</div>
            <div style="height:6px;background:rgba(255,255,255,0.08);border-radius:3px;margin-top:8px;overflow:hidden">
                <div style="width:{bar_w}%;height:100%;background:{color};border-radius:3px"></div>
            </div>
            {"<div style='font-size:.65rem;color:var(--red);margin-top:4px'>&#x25BC; Lowest signal</div>" if label == lowest_key else ""}
        </div>''')
    indicator_html = f'''
    <div style="margin-bottom:20px">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px">Indicator Signal Averages</div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">{"".join(ind_cols)}</div>
    </div>'''

    # ── Score distribution table ──
    dist_rows = ""
    if score_dist:
        for bucket, count in sorted(score_dist.items()):
            bar_w = min(int(count / max(score_dist.values()) * 80), 80) if max(score_dist.values()) > 0 else 0
            dist_rows += f'''<tr>
                <td style="padding:7px 10px;font-family:monospace;color:var(--muted)">{bucket}</td>
                <td style="padding:7px 10px;font-weight:600">{count}</td>
                <td style="padding:7px 10px">
                    <div style="height:10px;background:rgba(255,255,255,0.05);border-radius:3px;overflow:hidden;width:120px">
                        <div style="width:{bar_w}%;height:100%;background:var(--blue);border-radius:3px"></div>
                    </div>
                </td>
            </tr>'''
    dist_html = ""
    if dist_rows:
        dist_html = f'''
        <div style="margin-bottom:20px">
            <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px">Score Distribution</div>
            <table style="border-collapse:collapse;font-size:.82rem;width:100%">
                <thead><tr>
                    <th style="text-align:left;padding:8px 10px;font-size:.65rem;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)">Bucket</th>
                    <th style="text-align:left;padding:8px 10px;font-size:.65rem;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)">Count</th>
                    <th style="text-align:left;padding:8px 10px;font-size:.65rem;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)">Distribution</th>
                </tr></thead>
                <tbody>{dist_rows}</tbody>
            </table>
        </div>'''

    # ── Threshold impact table ──
    thresh_rows = ""
    if threshold_impact:
        for t_key in ["0.30", "0.35", "0.40", "0.45", "0.50"]:
            if t_key in threshold_impact:
                t_val = threshold_impact[t_key]
                t_float = float(t_key)
                is_current = abs(t_float - current_threshold) < 0.01
                passes = t_val.get("passes", 0) if isinstance(t_val, dict) else t_val
                delta = passes - score_pass if isinstance(passes, (int, float)) else ""
                delta_str = f"+{delta}" if isinstance(delta, (int, float)) and delta > 0 else str(delta) if isinstance(delta, (int, float)) else ""
                delta_color = "var(--green)" if isinstance(delta, (int, float)) and delta > 0 else "var(--red)" if isinstance(delta, (int, float)) and delta < 0 else "var(--muted)"
                row_style = "background:rgba(59,130,246,0.08)" if is_current else ""
                current_marker = " &#x25C4; current" if is_current else ""
                thresh_rows += f'''<tr style="{row_style}">
                    <td style="padding:7px 10px;font-family:monospace;font-weight:{'700' if is_current else '400'}">{t_key}{current_marker}</td>
                    <td style="padding:7px 10px">{passes}</td>
                    <td style="padding:7px 10px;color:{delta_color}">{delta_str}</td>
                </tr>'''
    thresh_html = ""
    if thresh_rows:
        thresh_html = f'''
        <div style="margin-bottom:20px">
            <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px">Threshold Impact Analysis</div>
            <table style="border-collapse:collapse;font-size:.82rem;width:100%;max-width:400px">
                <thead><tr>
                    <th style="text-align:left;padding:8px 10px;font-size:.65rem;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)">Threshold</th>
                    <th style="text-align:left;padding:8px 10px;font-size:.65rem;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)">Passes</th>
                    <th style="text-align:left;padding:8px 10px;font-size:.65rem;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)">Delta vs Current</th>
                </tr></thead>
                <tbody>{thresh_rows}</tbody>
            </table>
        </div>'''

    # ── LLM Diagnosis ──
    diagnosis_html = f'''
    <div style="margin-bottom:8px">
        <div style="font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px">LLM Diagnosis</div>
        <blockquote style="margin:0;padding:16px 20px;background:rgba(139,92,246,0.08);border-left:4px solid var(--purple);border-radius:0 10px 10px 0;font-size:.9rem;line-height:1.6;color:var(--text);font-style:italic">{llm_summary}</blockquote>
    </div>'''

    return f'''
    <div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F52C; SwarmLearner Insights</span>
            <span class="section-badge">{total} decisions analyzed</span>
            <span class="section-line"></span>
        </div>
        {bottleneck_html}
        {funnel_html}
        {indicator_html}
        {dist_html}
        {thresh_html}
        {diagnosis_html}
    </div>'''


def _build_llm_stats_section(llm_stats: dict) -> str:
    """Build the LLM Cost Monitor card for the Pulse tab."""
    if not llm_stats or not llm_stats.get("by_agent"):
        return ""

    today_total = llm_stats.get("today_total", 0)
    hourly_total = llm_stats.get("hourly_total", 0)
    by_agent = llm_stats.get("by_agent", {})

    # Color thresholds for hourly total
    if hourly_total > 100_000:
        hour_color = "var(--red)"
    elif hourly_total > 50_000:
        hour_color = "var(--yellow)"
    else:
        hour_color = "var(--green)"

    # Build per-agent rows
    agent_rows = ""
    for agent, stats in sorted(by_agent.items(), key=lambda x: x[1].get("today", 0), reverse=True):
        today_tok = stats.get("today", 0)
        hour_tok = stats.get("hour", 0)
        cost_eur = stats.get("cost_eur_today", 0)
        calls = stats.get("calls_today", 0)
        if today_tok == 0 and calls == 0:
            continue
        hour_color_agent = "var(--red)" if hour_tok > 100_000 else ("var(--yellow)" if hour_tok > 50_000 else "var(--muted)")
        agent_rows += f'''
        <tr>
            <td style="padding:6px 8px;font-weight:500">{agent}</td>
            <td style="padding:6px 8px;text-align:right">{today_tok:,}</td>
            <td style="padding:6px 8px;text-align:right;color:{hour_color_agent}">{hour_tok:,}</td>
            <td style="padding:6px 8px;text-align:right">{calls}</td>
            <td style="padding:6px 8px;text-align:right;color:var(--yellow)">€{cost_eur:.4f}</td>
        </tr>'''

    if not agent_rows:
        return ""

    return f'''
<div class="section" style="margin-top:16px">
    <div class="section-header">
        <span class="section-title">&#x1F4B8; LLM Cost Monitor</span>
        <span class="section-badge">Today: {today_total:,} tokens</span>
        <span style="margin-left:auto;font-size:.8rem;color:{hour_color}">This hour: {hourly_total:,} tokens</span>
        <span class="section-line"></span>
    </div>
    <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:.85rem">
            <thead>
                <tr style="border-bottom:1px solid rgba(255,255,255,0.1);color:var(--muted)">
                    <th style="padding:6px 8px;text-align:left">Agent</th>
                    <th style="padding:6px 8px;text-align:right">Tokens Today</th>
                    <th style="padding:6px 8px;text-align:right">Tokens/Hour</th>
                    <th style="padding:6px 8px;text-align:right">Calls Today</th>
                    <th style="padding:6px 8px;text-align:right">Est. Cost Today</th>
                </tr>
            </thead>
            <tbody>{agent_rows}
            </tbody>
        </table>
    </div>
    <div style="font-size:.75rem;color:var(--muted);margin-top:8px">
        ⚠️ Yellow = &gt;50K tokens/hr &nbsp;|&nbsp; 🔴 Red = &gt;100K tokens/hr &nbsp;|&nbsp; Cost estimate: €0.125/1M tokens blended
    </div>
</div>'''


def _build_pnl_charts(trades, pnl_snapshots):
    """Build daily realized P&L bar chart and unrealized P&L line chart."""
    import json as _json
    from collections import defaultdict
    from datetime import datetime as _dt, timedelta as _td

    # ── Realized P&L by day (last 30 days) ─────────────────────────────
    daily_pnl = defaultdict(float)
    for t in trades:
        if t.get('status', '').startswith('CLOSED') or t.get('status') == 'CLOSED':
            pnl = t.get('pnl') or 0
            if pnl == 0:
                continue
            exit_time = t.get('exit_time') or t.get('entry_fmt', '')
            try:
                day = _dt.fromisoformat(exit_time).strftime('%Y-%m-%d')
                daily_pnl[day] += pnl
            except Exception:
                pass

    # Generate last 30 days
    today = _dt.now().date()
    days = [(today - _td(days=i)).isoformat() for i in range(29, -1, -1)]
    realized_vals = [round(daily_pnl.get(d, 0), 2) for d in days]
    cumulative = []
    running = 0.0
    for v in realized_vals:
        running += v
        cumulative.append(round(running, 2))
    bar_colors = ['rgba(16,185,129,0.7)' if v >= 0 else 'rgba(239,68,68,0.7)' for v in realized_vals]
    bar_border = ['#10b981' if v >= 0 else '#ef4444' for v in realized_vals]
    short_days = [d[5:] for d in days]  # MM-DD

    # ── Unrealized P&L snapshots ────────────────────────────────────────
    unreal_html = ''
    if pnl_snapshots:
        snap_days   = [s['date'][5:] for s in pnl_snapshots[-30:]]
        snap_vals   = [s.get('unrealized_pnl', 0) for s in pnl_snapshots[-30:]]
        snap_colors = ['rgba(59,130,246,0.7)' if v >= 0 else 'rgba(239,68,68,0.7)' for v in snap_vals]
        unreal_html = f'''
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:20px">
            <div style="font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:14px">
                Unrealized P&amp;L — Daily Snapshot (last {len(snap_days)} days)
            </div>
            <div style="position:relative;height:160px"><canvas id="chartUnreal"></canvas></div>
        </div>
        <script>
        new Chart(document.getElementById('chartUnreal'), {{
            type: 'bar',
            data: {{
                labels: {_json.dumps(snap_days)},
                datasets: [{{
                    label: 'Unrealized P&L ($)',
                    data: {_json.dumps(snap_vals)},
                    backgroundColor: {_json.dumps(snap_colors)},
                    borderRadius: 3
                }}]
            }},
            options: {{
                responsive: true, maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#9ca3af', font: {{ size: 10 }}, maxRotation: 45 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
                    y: {{ ticks: {{ color: '#9ca3af', font: {{ size: 10 }}, callback: v => '$' + v.toFixed(0) }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
                }}
            }}
        }});
        </script>'''

    if not any(v != 0 for v in realized_vals) and not unreal_html:
        return ''

    realized_html = ''
    if any(v != 0 for v in realized_vals):
        realized_html = f'''
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:20px">
            <div style="font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:14px">
                Daily Realized P&amp;L — last 30 days
            </div>
            <div style="position:relative;height:160px"><canvas id="chartDaily"></canvas></div>
        </div>
        <div style="background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:20px">
            <div style="font-size:.75rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:14px">
                Cumulative Realized P&amp;L
            </div>
            <div style="position:relative;height:140px"><canvas id="chartCumul"></canvas></div>
        </div>
        <script>
        new Chart(document.getElementById('chartDaily'), {{
            type: 'bar',
            data: {{
                labels: {_json.dumps(short_days)},
                datasets: [{{
                    label: 'Daily P&L ($)',
                    data: {_json.dumps(realized_vals)},
                    backgroundColor: {_json.dumps(bar_colors)},
                    borderColor: {_json.dumps(bar_border)},
                    borderWidth: 1, borderRadius: 3
                }}]
            }},
            options: {{
                responsive: true, maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#9ca3af', font: {{ size: 10 }}, maxRotation: 45 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
                    y: {{ ticks: {{ color: '#9ca3af', font: {{ size: 10 }}, callback: v => '$' + v.toFixed(0) }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
                }}
            }}
        }});
        new Chart(document.getElementById('chartCumul'), {{
            type: 'line',
            data: {{
                labels: {_json.dumps(short_days)},
                datasets: [{{
                    label: 'Cumulative P&L ($)',
                    data: {_json.dumps(cumulative)},
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59,130,246,0.1)',
                    fill: true, tension: 0.3, pointRadius: 2
                }}]
            }},
            options: {{
                responsive: true, maintainAspectRatio: false,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#9ca3af', font: {{ size: 10 }}, maxRotation: 45 }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }},
                    y: {{ ticks: {{ color: '#9ca3af', font: {{ size: 10 }}, callback: v => '$' + v.toFixed(0) }}, grid: {{ color: 'rgba(75,85,99,0.2)' }} }}
                }}
            }}
        }});
        </script>'''

    return f'''<div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F4C8; P&amp;L Charts</span>
            <span class="section-line"></span>
        </div>
        {realized_html}
        {unreal_html}
    </div>'''


def _build_trades_section(trades, positions_status=None, pnl_snapshots=None):
    """Build the Trades tab: open positions (two tables by P&L) + pending + paginated history."""
    import time as _time
    positions_status = positions_status or {}
    pnl_snapshots = pnl_snapshots or []

    if not trades:
        return '''<div class="section">
            <div class="section-header">
                <span class="section-title">&#x1F4B0; Trades</span>
                <span class="section-badge">0 trades</span>
                <span class="section-line"></span>
            </div>
            <p style="color:var(--muted);padding:24px 0">No trades recorded yet.</p>
        </div>'''

    def _ts(t):
        v = t.get('exit_time') or t.get('entry_time', 0)
        if isinstance(v, str):
            try:
                from datetime import datetime as _dt2
                return _dt2.fromisoformat(v).timestamp()
            except Exception:
                return 0.0
        return float(v or 0)

    def _is_closed(t):
        s = t.get('status', '')
        return s == 'CLOSED' or s.startswith('CLOSED (')

    open_trades    = sorted(
        [t for t in trades if t.get('status') in ('OPEN', 'PLACED')],
        key=lambda t: positions_status.get(t.get('ticker', ''), {}).get('pnl_pct', 0),
        reverse=True
    )
    pending_trades = [t for t in trades if t.get('status') == 'PENDING_FOUNDER_APPROVAL']
    closed_trades  = sorted(
        [t for t in trades if _is_closed(t)],
        key=_ts, reverse=True
    )
    other_trades = sorted(
        [t for t in trades if not _is_closed(t) and t.get('status') not in ('OPEN', 'PLACED', 'PENDING_FOUNDER_APPROVAL')],
        key=_ts, reverse=True
    )

    sections = []

    # ── helpers ──────────────────────────────────────────────────────────────
    TH = '<th style="text-align:left;padding:7px 10px;white-space:nowrap">'

    def _pos_row(t):
        ticker    = t.get('ticker', '?')
        action    = (t.get('action') or 'BUY').upper()
        direction = 'LONG' if action == 'BUY' else 'SHORT'
        dir_color = 'var(--green)' if action == 'BUY' else 'var(--red)'
        tf        = t.get('timeframe', '—')
        entry     = t.get('entry_price') or t.get('intended_price', 0)
        qty       = t.get('quantity', 0)
        value     = t.get('trade_value') or (entry * qty)
        tp        = t.get('take_profit', 0)
        sl        = t.get('stop_loss', 0)
        entry_ts  = t.get('entry_time', 0)

        ps             = positions_status.get(ticker, {})
        current_price  = ps.get('current_price')
        unrealized_pnl = ps.get('unrealized_pnl')
        pnl_pct        = ps.get('pnl_pct')

        elapsed = '—'
        if entry_ts:
            secs    = int(_time.time() - entry_ts)
            elapsed = f"{secs // 3600}h {(secs % 3600) // 60}m" if secs >= 3600 else f"{secs // 60}m"

        tp_html    = f'<span style="color:var(--green)">${tp:.4f}</span>' if tp else '<span style="color:var(--muted)">—</span>'
        sl_stage   = t.get('sl_stage', 0)
        sl_labels  = {1: ('<span style="font-size:.68rem;background:rgba(245,158,11,.2);color:#f59e0b;border-radius:3px;padding:1px 4px;margin-left:4px">BE</span>', ),
                      2: ('<span style="font-size:.68rem;background:rgba(16,185,129,.2);color:var(--green);border-radius:3px;padding:1px 4px;margin-left:4px">Trail</span>', )}
        sl_badge   = sl_labels.get(sl_stage, ('',))[0]
        sl_html    = (f'<span style="color:var(--red)">${sl:.4f}</span>{sl_badge}' if sl else '<span style="color:var(--muted)">—</span>')
        price_html = f'${current_price:.4f}' if current_price else '<span style="color:var(--muted)">—</span>'
        partial_badge = '<span style="font-size:.68rem;background:rgba(59,130,246,.2);color:var(--blue,#3b82f6);border-radius:3px;padding:1px 4px;margin-left:5px">½ taken</span>' if t.get('partial_tp1_taken') else ''

        if unrealized_pnl is not None:
            upnl_color = 'var(--green)' if unrealized_pnl >= 0 else 'var(--red)'
            sign       = '+' if unrealized_pnl >= 0 else ''
            upnl_html  = f'<span style="color:{upnl_color};font-weight:600">{sign}${unrealized_pnl:.2f} ({sign}{pnl_pct:.1f}%)</span>'
        else:
            upnl_html = '<span style="color:var(--muted)">—</span>'

        warn = ''
        if current_price and tp and sl:
            tp_dist = abs(tp - current_price) / current_price * 100
            sl_dist = abs(sl - current_price) / current_price * 100
            if sl_dist < 2:
                warn = ' &#x26A0;&#xFE0F;'
            elif tp_dist < 2:
                warn = ' &#x1F3AF;'

        return (unrealized_pnl or 0.0, f'''<tr style="border-bottom:1px solid var(--border);font-size:.82rem">
            <td style="padding:7px 10px;font-weight:600">{ticker}{warn}{partial_badge}</td>
            <td style="padding:7px 10px;color:var(--muted)">{tf}</td>
            <td style="padding:7px 10px"><span style="color:{dir_color}">{direction}</span></td>
            <td style="padding:7px 10px">${entry:.4f}</td>
            <td style="padding:7px 10px">{price_html}</td>
            <td style="padding:7px 10px">{tp_html}</td>
            <td style="padding:7px 10px">{sl_html}</td>
            <td style="padding:7px 10px;color:var(--muted)">${value:.2f}</td>
            <td style="padding:7px 10px">{upnl_html}</td>
            <td style="padding:7px 10px;color:var(--muted)">{elapsed}</td>
        </tr>''')

    def _pos_table(rows_html, title, color):
        if not rows_html:
            return ''
        header_cols = ['Ticker', 'TF', 'Dir', 'Entry', 'Current', 'TP', 'SL', 'Value', 'Unreal. P&amp;L', 'Open']
        ths = ''.join(f'{TH}{c}</th>' for c in header_cols)
        return f'''<div style="margin-bottom:18px">
            <div style="font-size:.78rem;font-weight:700;color:{color};text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">{title}</div>
            <div style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse">
                <thead><tr style="color:var(--muted);font-size:.7rem;text-transform:uppercase;border-bottom:1px solid var(--border)">{ths}</tr></thead>
                <tbody>{"".join(rows_html)}</tbody>
            </table>
            </div></div>'''

    # ── Open Positions ────────────────────────────────────────────────────────
    if open_trades:
        pos_rows      = [_pos_row(t) for t in open_trades]
        total_unreal  = sum(p for p, _ in pos_rows)
        profit_rows   = [html for p, html in pos_rows if p >= 0]
        loss_rows     = [html for p, html in pos_rows if p < 0]

        upnl_color = 'var(--green)' if total_unreal >= 0 else 'var(--red)'
        upnl_sign  = '+' if total_unreal >= 0 else ''
        total_strip = f'''<div style="display:flex;gap:28px;padding:8px 0 16px;flex-wrap:wrap">
            <div><div style="color:var(--muted);font-size:.72rem;margin-bottom:2px">OPEN POSITIONS</div><div style="font-weight:700;font-size:1.1rem">{len(open_trades)}</div></div>
            <div><div style="color:var(--muted);font-size:.72rem;margin-bottom:2px">TOTAL UNREALIZED P&amp;L</div><div style="font-weight:700;font-size:1.1rem;color:{upnl_color}">{upnl_sign}${total_unreal:.2f}</div></div>
        </div>'''

        tables_html = _pos_table(profit_rows, '&#x1F7E2; Profitable', 'var(--green)') + \
                      _pos_table(loss_rows,   '&#x1F534; Losing',     'var(--red)')

        sections.append(f'''<div class="section">
            <div class="section-header">
                <span class="section-title">&#x1F7E2; Open Positions</span>
                <span class="section-badge">{len(open_trades)}</span>
                <span class="section-line"></span>
            </div>
            {total_strip}
            {tables_html}
        </div>''')
    else:
        sections.append('''<div class="section">
            <div class="section-header">
                <span class="section-title">&#x1F7E2; Open Positions</span>
                <span class="section-badge">0</span>
                <span class="section-line"></span>
            </div>
            <p style="color:var(--muted);padding:12px 0">No open positions.</p>
        </div>''')

    # ── Pending Approval ──────────────────────────────────────────────────────
    if pending_trades:
        rows = []
        for t in pending_trades:
            ticker    = t.get('ticker', '?')
            action    = (t.get('action') or 'BUY').upper()
            direction = 'LONG' if action == 'BUY' else 'SHORT'
            dir_color = 'var(--green)' if action == 'BUY' else 'var(--red)'
            price     = t.get('intended_price', 0)
            value     = t.get('trade_value', 0)
            rows.append(f'''<tr style="border-bottom:1px solid var(--border)">
                <td style="padding:10px 12px;font-weight:600">{ticker}</td>
                <td style="padding:10px 12px"><span style="color:{dir_color}">{direction}</span></td>
                <td style="padding:10px 12px">${price:.4f}</td>
                <td style="padding:10px 12px">${value:.2f}</td>
                <td style="padding:10px 12px"><span style="color:var(--yellow)">&#x23F3; Awaiting Approval</span></td>
            </tr>''')
        sections.append(f'''<div class="section">
            <div class="section-header">
                <span class="section-title">&#x23F3; Pending Approval</span>
                <span class="section-badge">{len(pending_trades)}</span>
                <span class="section-line"></span>
            </div>
            <div style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse;font-size:.85rem">
                <thead><tr style="color:var(--muted);font-size:.72rem;text-transform:uppercase;border-bottom:1px solid var(--border)">
                    {TH}Ticker</th>{TH}Direction</th>{TH}Intended Price</th>{TH}Value</th>{TH}Status</th>
                </tr></thead>
                <tbody>{"".join(rows)}</tbody>
            </table>
            </div>
        </div>''')

    # ── Trade History (paginated, newest first) ───────────────────────────────
    history = closed_trades + other_trades   # both already sorted newest-first
    if history:
        wins      = sum(1 for t in closed_trades if (t.get('pnl') or 0) > 0)
        losses    = sum(1 for t in closed_trades if (t.get('pnl') or 0) < 0)
        no_data   = len(closed_trades) - wins - losses
        total_pnl = sum(t.get('pnl') or 0 for t in closed_trades)
        scored    = wins + losses  # trades with actual PnL data
        win_rate  = (wins / scored * 100) if scored else 0
        pnl_color = 'var(--green)' if total_pnl >= 0 else 'var(--red)'
        wr_color  = 'var(--green)' if win_rate >= 50 else 'var(--red)'
        no_data_html = f' / <span style="color:var(--muted)">{no_data} n/a</span>' if no_data else ''

        stats_bar = f'''<div style="display:flex;gap:28px;padding:12px 0 20px;flex-wrap:wrap">
            <div><div style="color:var(--muted);font-size:.72rem;margin-bottom:2px">CLOSED TRADES</div><div style="font-weight:700;font-size:1.1rem">{len(closed_trades)}</div></div>
            <div><div style="color:var(--muted);font-size:.72rem;margin-bottom:2px">WIN RATE</div><div style="font-weight:700;font-size:1.1rem;color:{wr_color}">{win_rate:.0f}%</div></div>
            <div><div style="color:var(--muted);font-size:.72rem;margin-bottom:2px">TOTAL P&amp;L</div><div style="font-weight:700;font-size:1.1rem;color:{pnl_color}">{"+" if total_pnl >= 0 else ""}${total_pnl:.2f}</div></div>
            <div><div style="color:var(--muted);font-size:.72rem;margin-bottom:2px">WINS / LOSSES</div><div style="font-weight:700;font-size:1.1rem"><span style="color:var(--green)">{wins}W</span> / <span style="color:var(--red)">{losses}L</span>{no_data_html}</div></div>
        </div>'''

        rows = []
        for t in history:
            ticker     = t.get('ticker', '?')
            action     = (t.get('action') or 'BUY').upper()
            direction  = 'LONG' if action == 'BUY' else 'SHORT'
            dir_color  = 'var(--green)' if action == 'BUY' else 'var(--red)'
            tf         = t.get('timeframe', '—')
            entry      = t.get('entry_price') or t.get('intended_price', 0)
            exit_price = t.get('exit_price', 0)
            pnl        = t.get('pnl') or 0
            pnl_pct    = t.get('pnl_percent') or 0
            status     = t.get('status', '?')
            pnl_color  = 'var(--green)' if pnl > 0 else ('var(--red)' if pnl < 0 else 'var(--muted)')
            pnl_sign   = '+' if pnl > 0 else ''

            entry_ts = t.get('entry_time', 0)
            exit_ts  = t.get('exit_time', 0)
            duration = '—'
            try:
                if isinstance(exit_ts, str):
                    from datetime import datetime as _dt
                    exit_ts = _dt.fromisoformat(exit_ts).timestamp()
                if entry_ts and exit_ts:
                    secs     = int(float(exit_ts) - float(entry_ts))
                    duration = f"{secs // 3600}h {(secs % 3600) // 60}m" if secs >= 3600 else f"{secs // 60}m"
            except Exception:
                pass

            close_reason = t.get('close_reason', '')
            if not close_reason and status.startswith('CLOSED ('):
                close_reason = status[8:-1]  # extract from old "CLOSED (reason)" format
            if _is_closed(t):
                reason_label = {'Take_Profit': '&#x1F3AF; TP', 'Stop_Loss': '&#x1F6D1; SL',
                                'DISPLACED_BY_HIGHER_CONVICTION': '&#x1F504; Displaced',
                                'MANUAL': '&#x270D; Manual'}.get(close_reason, close_reason or 'Closed')
                status_html = f'<span style="color:var(--muted)">{reason_label}</span>'
            elif status == 'EXPIRED':
                status_html = '<span style="color:var(--yellow)">Expired</span>'
            else:
                status_html = f'<span style="color:var(--muted)">{status}</span>'
            exit_html   = f'${exit_price:.4f}' if exit_price else '—'

            pg = len(rows) // 20   # 0-based page index for this row
            display = 'table-row' if pg == 0 else 'none'
            rows.append(f'''<tr class="hist-row" data-pg="{pg}" style="display:{display};border-bottom:1px solid var(--border)">
                <td style="padding:8px 10px;font-weight:600">{ticker}</td>
                <td style="padding:8px 10px;color:var(--muted)">{tf}</td>
                <td style="padding:8px 10px"><span style="color:{dir_color}">{direction}</span></td>
                <td style="padding:8px 10px">${entry:.4f}</td>
                <td style="padding:8px 10px">{exit_html}</td>
                <td style="padding:8px 10px;color:{pnl_color};font-weight:600">{pnl_sign}${pnl:.2f}</td>
                <td style="padding:8px 10px;color:{pnl_color}">{pnl_sign}{pnl_pct:.1f}%</td>
                <td style="padding:8px 10px;color:var(--muted)">{duration}</td>
                <td style="padding:8px 10px">{status_html}</td>
            </tr>''')

        total_rows  = len(rows)
        page_size   = 20
        total_pages = max(1, (total_rows + page_size - 1) // page_size)

        pagination_js = f'''<script>
(function() {{
  var cur = 0;
  var total = {total_pages};
  function show(p) {{
    cur = p;
    var trs = document.querySelectorAll('#hist-tbody .hist-row');
    for (var i = 0; i < trs.length; i++) {{
      trs[i].style.display = (parseInt(trs[i].dataset.pg) === p) ? 'table-row' : 'none';
    }}
    document.getElementById('hist-page-info').textContent = 'Page ' + (p+1) + ' of ' + total;
    document.getElementById('hist-prev').disabled = (p === 0);
    document.getElementById('hist-next').disabled = (p === total - 1);
  }}
  document.getElementById('hist-prev').addEventListener('click', function() {{ if (cur > 0) show(cur - 1); }});
  document.getElementById('hist-next').addEventListener('click', function() {{ if (cur < total - 1) show(cur + 1); }});
  show(0);
}})();
</script>'''

        sections.append(f'''<div class="section">
            <div class="section-header">
                <span class="section-title">&#x1F4DC; Trade History</span>
                <span class="section-badge">{total_rows} trades</span>
                <span class="section-line"></span>
            </div>
            {stats_bar}
            <div style="overflow-x:auto">
            <table style="width:100%;border-collapse:collapse;font-size:.83rem">
                <thead><tr style="color:var(--muted);font-size:.7rem;text-transform:uppercase;border-bottom:1px solid var(--border)">
                    {TH}Ticker</th>{TH}TF</th>{TH}Dir</th>{TH}Entry</th>{TH}Exit</th>
                    {TH}P&amp;L</th>{TH}P&amp;L %</th>{TH}Duration</th>{TH}Status</th>
                </tr></thead>
                <tbody id="hist-tbody">{"".join(rows)}</tbody>
            </table>
            </div>
            <div style="display:flex;align-items:center;gap:12px;padding:12px 0 4px;font-size:.82rem">
                <button id="hist-prev" style="padding:4px 14px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer">&#8592; Prev</button>
                <span id="hist-page-info" style="color:var(--muted)"></span>
                <button id="hist-next" style="padding:4px 14px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer">Next &#8594;</button>
            </div>
            {pagination_js}
        </div>''')

    charts_html = _build_pnl_charts(trades, pnl_snapshots)
    if charts_html:
        sections.insert(0, charts_html)

    return "\n".join(sections)


def _build_dashboard_html(agents, backlog_items=None, open_opportunities=None, learning_data=None, trades=None, positions_status=None, llm_stats=None, pnl_snapshots=None):
    """Build dashboard HTML with pipeline and supporting agent sections."""
    # Index agents by name
    agent_map = {}
    for a in agents:
        agent_map[a.get("agent_name", "Unknown")] = a

    # Build pipeline section (ordered)
    pipeline_cards = []
    flow_steps = []
    for idx, name in enumerate(PIPELINE_ORDER):
        agent = agent_map.pop(name, None)
        if agent:
            pipeline_cards.append(_build_agent_card(agent, step_num=idx + 1))
            status = agent.get("status", "IDLE")
            css = "flow-active" if status in ("ACTIVE", "WORKING") else ""
            flow_steps.append(f'<span class="flow-step {css}">{ICONS.get(name, "")} {PIPELINE_LABELS.get(name, name)}</span>')

    # Flow bar
    flow_html = '<div class="pipeline-flow">' + ' <span class="flow-arrow">&#x2192;</span> '.join(flow_steps) + '</div>' if flow_steps else ""

    # Build supporting section (remaining agents)
    supporting_cards = []
    for name, agent in agent_map.items():
        supporting_cards.append(_build_agent_card(agent))

    # Extract ProjectLead decisions
    project_lead_decisions = []
    for a in agents:
        if a.get("agent_name") == "ProjectLead":
            meta = a.get("metadata") or {}
            project_lead_decisions = meta.get("latest_decisions", [])
            break

    # ── Build all sections ──

    # Read adaptive score threshold
    _score_threshold = 0.40
    try:
        with open("core/agent_weights.json") as _wf:
            _score_threshold = float(json.load(_wf).get("score_threshold", 0.40))
    except Exception:
        pass

    # 1. Health banner (compact strip for Pulse tab)
    health_banner = _build_health_banner(agents)
    health_banner += (
        f'<div class="health-strip boot" style="cursor:default;margin-top:6px">'
        f'&#x1F4CA; Score Threshold: <strong style="color:var(--purple)">{_score_threshold:.3f}</strong>'
        f'&ensp;&mdash;&ensp;auto-tuned by PerformanceAuditor (floor&nbsp;0.32&nbsp;/&nbsp;ceil&nbsp;0.48)'
        f'</div>'
    )

    # 3. Decisions section (new tab — layman language)
    decisions_section = _build_decisions_section(project_lead_decisions)

    # 4. Opportunities section (improved — USDT filtered, trade probability)
    opportunities_section = _build_opportunities_section(open_opportunities)

    # 5. Pipeline section
    pipeline_section = f'''<div class="section">
        <div class="section-header">
            <span class="section-title">&#x26A1; Pipeline Agents</span>
            <span class="section-badge">{len(pipeline_cards)} agents</span>
            <span class="section-line"></span>
        </div>
        {flow_html}
        <div class="grid">{chr(10).join(pipeline_cards)}</div>
    </div>'''

    # 6. Supporting section
    supporting_section = ""
    if supporting_cards:
        supporting_section = f'''<div class="section">
        <div class="section-header">
            <span class="section-title">&#x1F527; Supporting Agents</span>
            <span class="section-badge">{len(supporting_cards)} agents &bull; called by pipeline</span>
            <span class="section-line"></span>
        </div>
        <div class="grid">{chr(10).join(supporting_cards)}</div>
    </div>'''

    # 8. CPO section
    cpo_section = _build_cpo_section(backlog_items or [])

    # 12. SwarmLearner Insights section
    learner_section = _build_swarm_learner_section(learning_data or {})

    # 13. Trades section
    trades_section = _build_trades_section(trades or [], positions_status or {}, pnl_snapshots or [])

    # 14. LLM Cost Monitor section
    llm_stats_section = _build_llm_stats_section(llm_stats or {})

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (HTML_TEMPLATE
        .replace("{timestamp}", now)
        .replace("{health_banner}", health_banner)
        .replace("{pipeline_section}", pipeline_section)
        .replace("{opportunities_section}", opportunities_section)
        .replace("{decisions_section}", decisions_section)
        .replace("{cpo_section}", cpo_section)
        .replace("{learner_section}", learner_section)
        .replace("{trades_section}", trades_section)
        .replace("{supporting_section}", supporting_section)
        .replace("{llm_stats_section}", llm_stats_section))



class DashboardHandler(BaseHTTPRequestHandler):
    db_client = None

    def do_GET(self):
        if self.path in ("/dashboard", "/dashboard/", "/"):
            try:
                # Read dashboard.json for open opportunities and LLM stats
                open_opportunities = []
                llm_stats_dash = {}
                import os, json
                if os.path.exists("dashboard.json"):
                    try:
                        with open("dashboard.json", "r") as f:
                            dash_data = json.load(f)
                        open_opportunities = dash_data.get("open_opportunities", [])
                        llm_stats_dash = dash_data.get("llm_stats", {})
                    except Exception as e:
                        pass
                        
                learning_data = {}
                if os.path.exists("learning_report.json"):
                    try:
                        with open("learning_report.json", "r") as f:
                            learning_data = json.load(f)
                    except Exception:
                        pass

                trades = []
                if os.path.exists("trade_log.json"):
                    try:
                        with open("trade_log.json", "r") as f:
                            trades = json.load(f)
                        if not isinstance(trades, list):
                            trades = []
                    except Exception:
                        pass

                positions_status = {}
                if os.path.exists("positions_status.json"):
                    try:
                        with open("positions_status.json", "r") as f:
                            positions_status = json.load(f)
                    except Exception:
                        pass

                pnl_snapshots = []
                if os.path.exists("pnl_snapshots.json"):
                    try:
                        with open("pnl_snapshots.json", "r") as f:
                            pnl_snapshots = json.load(f)
                    except Exception:
                        pass

                # Get Health
                agents = []
                backlog_items = []
                if self.db_client:
                    agents = self.db_client.get_swarm_health()
                    backlog_items = self.db_client.get_system_backlog(limit=20)

                html = _build_dashboard_html(agents, backlog_items, open_opportunities, learning_data, trades, positions_status, llm_stats=llm_stats_dash, pnl_snapshots=pnl_snapshots)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(f"Error: {e}".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default request logging


def start_dashboard_server(db_client, port=DASHBOARD_PORT):
    """Start the dashboard server in a background daemon thread."""
    DashboardHandler.db_client = db_client
    server = ThreadedHTTPServer(("0.0.0.0", port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Dashboard server started on port {port}")
    return server
