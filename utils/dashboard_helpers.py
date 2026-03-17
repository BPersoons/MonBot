"""
Dashboard helper functions for approval workflow
"""
import json
import streamlit as st
import time

DASHBOARD_FILE = "dashboard.json"

def load_data():
    """Reads the JSON data unless the file is missing."""
    import os
    if not os.path.exists(DASHBOARD_FILE):
        return None
    try:
        with open(DASHBOARD_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error reading dashboard data: {e}")
        return None

def approve_trade(trade_id):
    """Approve a pending trade."""
    data = load_data()
    if data:
        if 'approval_decisions' not in data:
            data['approval_decisions'] = {}
        
        data['approval_decisions'][trade_id] = 'APPROVED'
        
        # Remove from pending list
        if 'pending_approvals' in data:
            data['pending_approvals'] = [t for t in data['pending_approvals'] if t['trade_id'] != trade_id]
        
        try:
            with open(DASHBOARD_FILE, "w") as f:
                json.dump(data, f, indent=4)
            st.toast(f"✅ Trade {trade_id} APPROVED", icon="✅")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"Failed to approve trade: {e}")

def reject_trade(trade_id, reason="Founder rejection"):
    """Reject a pending trade."""
    data = load_data()
    if data:
        if 'approval_decisions' not in data:
            data['approval_decisions'] = {}
        
        data['approval_decisions'][trade_id] = f"REJECTED: {reason}"
        
        # Remove from pending list
        if 'pending_approvals' in data:
            data['pending_approvals'] = [t for t in data['pending_approvals'] if t['trade_id'] != trade_id]
        
        try:
            with open(DASHBOARD_FILE, "w") as f:
                json.dump(data, f, indent=4)
            st.toast(f"❌ Trade {trade_id} REJECTED", icon="❌")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"Failed to reject trade: {e}")
