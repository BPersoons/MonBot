import streamlit as st
import json
import time
import plotly.graph_objects as go
import os
from datetime import datetime
from utils.dashboard_helpers import approve_trade, reject_trade
from utils.dashboard_query_layer import DashboardDataProvider

# Page Config
st.set_page_config(
    page_title="Founder Control Tower",
    page_icon="🛡️",
    layout="wide",
)

# --- Constants & Setup ---
DASHBOARD_FILE = "dashboard.json"

# Initialize Data Provider
provider = DashboardDataProvider()

def load_data():
    """Reads the JSON data unless the file is missing."""
    if not os.path.exists(DASHBOARD_FILE):
        return None
    try:
        with open(DASHBOARD_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error reading dashboard data: {e}")
        return None

def save_status(status):
    """Updates the status in the JSON file (Kill Switch)."""
    data = load_data()
    if data:
        data['status'] = status
        # Also update the payload executive summary to reflect the override
        if 'payload_sent' in data:
            data['payload_sent']['executive_summary'] += f"\n\n🚨 [SYSTEM OVERRIDE] Status manually set to {status} by Founder."
            data['payload_sent']['risk_warning'] = status
        
        try:
            with open(DASHBOARD_FILE, "w") as f:
                json.dump(data, f, indent=4)
            st.toast(f"System status updated to: {status}", icon="🛑")
            time.sleep(1) # Give time for toast
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save status: {e}")

# --- Auto-Refresh Logic ---
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = time.time()

# Auto-refresh every 10 seconds (managed at bottom)

# --- Sidebar ---
with st.sidebar:
    st.header("Control Panel")
    if st.button("Refresh Now"):
        st.rerun()
    
    st.divider()
    
    # Show pending approval count
    data = load_data()
    if data:
        pending_count = len(data.get('pending_approvals', []))
        if pending_count > 0:
            st.warning(f"⏳ {pending_count} trade(s) awaiting approval")
            
    st.divider()
    
    # Database Health
    db_status = provider.get_system_status()
    db_ok = db_status.get("database_available", False)
    cache_mode = db_status.get("cache_mode", False)
    pending_writes = db_status.get("pending_writes", 0)
    
    st.subheader("Database Status")
    if db_ok:
        st.success("🟢 Supabase Connected")
    else:
        st.error("🔴 Supabase Disconnected")
        
    if cache_mode:
        st.warning(f"⚠️ Cache Mode Active\nPending writes: {pending_writes}")
    
    # KILL SWITCH
    st.divider()
    st.subheader("⚠️ DANGER ZONE")
    if st.button("KILL SWITCH (PAUSE SYSTEM)", type="primary"):
        save_status("PAUSED")
        
    if st.button("RESUME SYSTEM"):
        save_status("ACTIVE")
        
    st.info("System refreshes every 10s.")

# --- Main Layout ---
st.title("🛡️ Founder Control Tower")

data = load_data()

if not data:
    st.warning("No dashboard data found. Waiting for agents...")
    time.sleep(2)
    st.rerun()
else:
    # Global Status
    system_status = data.get("status", "ACTIVE")
    last_hb = data.get("last_heartbeat", "N/A")
    market_data = data.get("market_data", {})
    
    if system_status == "PAUSED":
        st.error("🛑 SYSTEM IS CURRENTLY PAUSED BY KILL SWITCH")
        
    st.caption(f"System Status: {system_status} | Last Heartbeat: {last_hb}")
    
    # Circuit Breaker Status
    from core.circuit_breaker import CircuitBreaker
    cb = CircuitBreaker()
    can_trade = cb.can_trade()
    
    if not can_trade:
        st.error("⛔ CIRCUIT BREAKER OPEN - Trading PAUSED by Circuit Breaker")
    
    # PENDING APPROVALS SECTION (HITL)
    st.divider()
    st.subheader("⏳ Pending Founder Approvals")
    
    pending_approvals = data.get('pending_approvals', [])
    
    if pending_approvals:
        st.warning(f"You have {len(pending_approvals)} trade(s) requiring approval")
        
        for idx, trade in enumerate(pending_approvals):
            with st.expander(f"🔔 {trade['ticker']} - ${trade['trade_value']:.2f} - {trade['action']}", expanded=True):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.markdown(f"**Ticker:** {trade['ticker']}")
                    st.markdown(f"**Action:** {trade['action']}")
                    st.markdown(f"**Quantity:** {trade['quantity']}")
                    st.markdown(f"**Price:** ${trade['price']:.2f}")
                    st.markdown(f"**Trade Value:** ${trade['trade_value']:.2f}")
                    st.markdown(f"**Conviction Score:** {trade.get('conviction', 0):.2f}")
                    st.caption(f"Submitted: {trade['timestamp']}")
                    
                    if trade.get('synthesis_report'):
                        with st.expander("📋 Synthesis Report (Agent Conflict)"):
                            st.code(trade['synthesis_report'], language="text")
                
                with col2:
                    st.markdown("**Actions**")
                    if st.button(f"✅ Approve", key=f"approve_{trade['trade_id']}", type="primary"):
                        approve_trade(trade['trade_id'])
                    if st.button(f"❌ Reject", key=f"reject_{trade['trade_id']}"):
                        reject_trade(trade['trade_id'], "Manual rejection by Founder")
                st.divider()
    else:
        st.success("✅ No pending approvals")
    
    st.divider()
    
    # --- 12-Hour Decision History Matrix ---
    history_file = "decision_history.json"
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                history_data = json.load(f)
            
            if history_data:
                st.subheader("🕒 12-Hour Near-Miss Trade Setups")
                
                import pandas as pd
                df = pd.DataFrame(history_data)
                df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)
                
                cutoff = datetime.now() - pd.Timedelta(hours=12)
                df = df[df['timestamp'] >= cutoff]
                
                # Filter out pure rejections
                if not df.empty and 'decision' in df.columns:
                    df = df[~df['decision'].isin(['NO_GO', 'SKIP', 'PENDING'])]
                
                if not df.empty:
                    df = df.sort_values(by='timestamp', ascending=False)
                    
                    def get_emoji(decision):
                        if decision == 'BUILD_CASE': return '🟢 ' + decision
                        elif decision == 'MONITOR': return '🟡 ' + decision
                        return '⚪ ' + str(decision)
                        
                    df['Status'] = df['decision'].apply(get_emoji)
                    
                    def format_setup(row):
                        target = row.get('target_entry_price', 0.0)
                        sl = row.get('stop_loss_pct', 0.0)
                        rrr = row.get('rrr', 'N/A')
                        try:
                            return f"Trgt: ${float(target):.4f} | SL: {sl}% | RRR {rrr}"
                        except:
                            return "N/A"
                            
                    def format_dist(row):
                        try:
                            target = float(row.get('target_entry_price', 0.0))
                            current = float(row.get('current_price', 0.0))
                            if target > 0 and current > 0:
                                dist = abs(target - current) / current * 100
                                return f"{dist:.2f}% (Now: ${current:.4f})"
                        except:
                            pass
                        return "N/A"
                        
                    df['Setup'] = df.apply(format_setup, axis=1)
                    df['Dist'] = df.apply(format_dist, axis=1)
                    
                    df['Time'] = df['timestamp'].dt.strftime('%H:%M:%S')
                    # Ensure columns exist even for older json payloads
                    if 'direction' not in df.columns: df['direction'] = "LONG"
                    
                    display_df = df[['Time', 'ticker', 'direction', 'Status', 'score', 'Setup', 'Dist', 'reason']]
                    display_df.columns = ['Time', 'Asset', 'Dir', 'Status', 'Score', 'Trade Setup', 'Dist to Entry', 'Rationale']
                    
                    st.dataframe(display_df, use_container_width=True, hide_index=True, height=250)
                else:
                    st.info("No near-miss trading decisions recorded in the last 12 hours.")
        except Exception as e:
            st.error(f"Error loading decision history: {e}")
            
    st.divider()
    
    if not market_data:
        st.info("No market data generated yet.")
    else:
        # 0. Multi-Asset Summary
        st.subheader("🌐 Market Overview")
        summary_rows = []
        for t, d in market_data.items():
            an = d.get('analysis', {})
            score = an.get('combined_score', 0)
            risk = d.get('risk_status', 'N/A')
            decision = d.get('status', 'N/A')
            summary_rows.append({"Asset": t, "Score": f"{score:.2f}", "Decision": decision, "Risk": risk})
        st.dataframe(summary_rows, hide_index=True)
        
        st.divider()

        # 1. Asset Selection
        assets = list(market_data.keys())
        default_index = 0
        if "BTC/USDT" in assets:
            default_index = assets.index("BTC/USDT")
            
        selected_asset = st.selectbox("Select Asset Detail", assets, index=default_index)
        
        asset_data = market_data[selected_asset]
        analysis = asset_data.get('analysis', {})
        details = analysis.get('details', {})
        payload = asset_data.get('payload_sent', {})
        
        # 1. Key Stats
        ticker = analysis.get('ticker', selected_asset)
        consensus = analysis.get('combined_score', 0.0)
        risk_status = asset_data.get('risk_status', 'UNKNOWN')
        
        status_color = "normal"
        if risk_status == "VEILIG": status_color = "off" # Green-ish
        elif risk_status == "PAUSED": status_color = "inverse" # Red
            
        col1, col2, col3 = st.columns(3)
        with col1: st.metric(label="Asset", value=ticker)
        with col2: st.metric(label="Consensus Score", value=f"{consensus:.2f}")
        with col3: st.metric(label="Risk Status", value=risk_status, delta="Live" if risk_status != "PAUSED" else "STOPPED", delta_color=status_color)

        st.divider()
        
        # 1.5 Team Reliability (Live from Supabase)
        st.subheader("⚖️ Team Reliability (Live Performance)")
        
        try:
            agent_scores = provider.get_agent_scores(days=30)
            
            w_metrics = st.columns(3)
            w_keys = ["technical", "fundamental", "sentiment"]
            
            for idx, key in enumerate(w_keys):
                score_data = agent_scores.get(key, {})
                accuracy = score_data.get('avg_accuracy', 0.0) # 0-1 range typically from calculation
                count = score_data.get('total_predictions', 0)
                
                with w_metrics[idx]:
                    st.metric(f"{key.capitalize()} Accuracy", f"{accuracy*100:.1f}%", f"{count} trades")
                    st.progress(max(0.0, min(1.0, accuracy)))
                    
        except Exception as e:
            st.error(f"Error loading agent scores: {e}")

        st.divider()

        # 2. Council View
        st.subheader(f"🏛️ The Council ({ticker})")
        
        t_agent = details.get('technical', {})
        f_agent = details.get('fundamental', {})
        s_agent = details.get('sentiment', {})
        
        c1, c2, c3 = st.columns(3)
        
        def display_agent(col, name, agent_data):
            with col:
                st.markdown(f"**{name}**")
                score = agent_data.get('signal', 0)
                reason = agent_data.get('reason', 'N/A')
                color = "gray"
                if score > 0.2: color = "green"
                elif score < -0.2: color = "red"
                st.markdown(f"<h2 style='color: {color}'>{score:+.2f}</h2>", unsafe_allow_html=True)
                st.caption(reason)
                
        display_agent(c1, "Technical Analyst", t_agent)
        display_agent(c2, "Fundamental Analyst", f_agent)
        display_agent(c3, "Sentiment Analyst", s_agent)

        # 3. Signal Heatmap
        st.subheader("📊 Signal Heatmap")
        agents = ['Technical', 'Fundamental', 'Sentiment']
        scores = [t_agent.get('signal', 0), f_agent.get('signal', 0), s_agent.get('signal', 0)]
        
        fig = go.Figure(data=go.Heatmap(
            z=[scores], x=agents, y=['Score'],
            colorscale='RdYlGn', zmin=-1, zmax=1,
            text=[[f"{s:+.2f}" for s in scores]], texttemplate="%{text}", showscale=False
        ))
        fig.update_layout(height=150, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

        # 4. Decision Log
        st.subheader("📜 Directieverslag (Decision Log)")
        exec_summary = payload.get('executive_summary', "No report available.")
        st.text_area("Last Report", value=exec_summary, height=150, disabled=True)
        
        # 4.5 Audit Log
        st.subheader("🛡️ Governance Audit Log")
        audit_file = "audit_log.txt"
        if os.path.exists(audit_file):
            with open(audit_file, "r") as f:
                logs = f.readlines()
                st.code("".join(logs[-10:]), language="text")
        else:
            st.info("No audit logs yet.")
            
    # 5. Discovery Pipeline
    st.subheader("🔬 Research & Discovery Pipeline")
    discovery = data.get("discovery_pipeline", {})
    last_scan = discovery.get("last_run", "Never")
    st.caption(f"Last Scan: {last_scan}")
    
    proposals = discovery.get("proposals", [])
    if proposals:
        prop_data = []
        for p in proposals:
            metrics = p.get('metrics', {})
            prop_data.append({
                "Ticker": p['ticker'],
                "Reason": p['reason'],
                "Sharpe": metrics.get('sharpe_ratio'),
                "Win Rate": f"{metrics.get('win_rate', 0)*100:.0f}%",
                "Est. 7d P&L": f"{metrics.get('total_pnl_pct', 0):.1f}%"
            })
        st.dataframe(prop_data, hide_index=True)
    else:
        st.info("No active proposals or pipeline is empty.")
    
    st.divider()

    # 6. Trade History (Supabase)
    st.subheader("📝 Recent Trades (Supabase)")
    
    try:
        trades = provider.get_latest_trades(limit=10)
        open_positions = provider.get_open_positions()
        
        # 6.1 Open Positions
        st.markdown("### Open Positions")
        if open_positions:
            open_data = []
            for t in open_positions:
                open_data.append({
                    "Ticker": t['ticker'],
                    "Action": t['action'],
                    "Qty": f"{t['quantity']:.6f}",
                    "Entry": f"${t['entry_price']:.2f}",
                    "Date": t['created_at'][:19].replace('T', ' ')
                })
            st.table(open_data)
        else:
            st.info("No open positions.")
            
        # 6.2 Recent History
        st.markdown("### Recent History")
        if trades:
            hist_data = []
            for t in trades:
                hist_data.append({
                    "Date": t['created_at'][:19].replace('T', ' '),
                    "Ticker": t['ticker'],
                    "Action": t['action'],
                    "Price": f"${t.get('entry_price', 0):.2f}",
                    "Status": t['status'],
                    "PnL": f"${t.get('pnl', 0):.2f}" if t['status'] == 'CLOSED' else '-'
                })
            st.dataframe(hist_data, hide_index=True)
        else:
            st.info("No trade history available yet.")
            
    except Exception as e:
        st.error(f"Error fetching trade data: {e}")

    # Last Update
    st.caption(f"Dashboard Refreshed: {time.strftime('%H:%M:%S')}")

# Auto-refresh mechanism at the bottom
time.sleep(10)
st.rerun()
