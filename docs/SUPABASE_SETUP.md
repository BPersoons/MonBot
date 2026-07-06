# Supabase Persistence Layer - Setup Guide

## Quick Start

### 1. Create Supabase Project

1. Go to [supabase.com](https://supabase.com)
2. Create a new project
3. Wait for database provisioning (~2 minutes)

### 2. Configure Environment

Update `.env.adk` with your Supabase credentials:

```bash
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_KEY=your-anon-public-key
```

**Where to find these:**
- Dashboard → Settings → API
- `URL`: Project URL
- `anon/public key`: Use the "anon public" key

### 3. Deploy Schema

**Option A: Supabase Dashboard (Recommended)**

1. Open your Supabase project
2. Navigate to **SQL Editor** (left sidebar)
3. Click **New Query**
4. Copy/paste the entire content of `integrations/supabase_schema.sql`
5. Click **Run**

**Option B: Display Schema**

```bash
python tests/test_supabase_connection.py --sql
```

### 4. Test Connection

```bash
python tests/test_supabase_connection.py
```

Expected output:
```
✅ Configuration Check
✅ Client Initialization
✅ Connection Test
✅ Schema Validation
✅ Write Test
✅ Read Test

🎉 ALL TESTS PASSED!
```

### 5. Verify CLI Commands

```bash
# Test connection
python -m utils.db_client --test-connection

# Validate schema
python -m utils.db_client --validate-schema

# Sync cache (if needed)
python -m utils.db_client --sync-cache
```

---

## Schema Overview

### Tables Created

1. **`trades`** - Trade execution history
   - Primary trade data (ticker, action, price, quantity, pnl)
   - ADK `reasoning_trace` (full decision chain)
   - Analyst signals and risk metrics

2. **`agent_performance`** - Analyst performance tracking
   - Prediction accuracy over time
   - Historical performance metrics
   - Dynamic weight calculation data

3. **`market_snapshots`** - Market data time series
   - Historical price/volume data
   - Technical indicators
   - Backtesting support

4. **`system_state`** - Global configuration
   - Active assets
   - System status
   - Feature flags

### Views Created

- `active_trades_summary` - Open positions summary
- `analyst_performance_summary` - 30-day performance stats
- `trade_pnl_summary` - P&L by ticker
- `recent_market_activity` - Last 24h market data

### Functions Created

- `get_win_rate(ticker)` - Calculate win rate for asset
- `get_analyst_reliability(analyst, days)` - Get analyst score

---

## Troubleshooting

### Connection Fails

**Error:** `❌ connection_available: False`

**Solutions:**
1. Verify `SUPABASE_URL` and `SUPABASE_KEY` in `.env.adk`
2. Check project is not paused (free tier auto-pauses after inactivity)
3. Verify IP is not blocked (Supabase firewall)
4. Check internet connection

### Schema Validation Fails

**Error:** `❌ schema_valid: False`

**Solutions:**
1. Run the schema SQL in Supabase dashboard
2. Check for SQL execution errors
3. Verify all tables were created:
   ```sql
   SELECT table_name FROM information_schema.tables 
   WHERE table_schema = 'public';
   ```

### Write Test Fails

**Error:** `❌ Write test failed`

**Solutions:**
1. Check Row Level Security (RLS) policies
2. Verify API key has write permissions
3. Check table constraints (action IN ('BUY', 'SELL', 'HOLD'))

### Supabase Library Not Installed

**Error:** `WARNING: Supabase library not installed`

**Solution:**
```bash
pip install supabase
```

Or reinstall all dependencies:
```bash
pip install -r requirements.txt
```

---

## Production Deployment

### 1. Enable Row Level Security (RLS)

For production, secure your tables:

```sql
-- Enable RLS
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_state ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "Service role access" ON trades
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);
```

### 2. Use Service Role Key

For backend/production, use the **service_role** key instead of anon key:

```bash
SUPABASE_KEY=your-service-role-secret-key
```

> **⚠️ WARNING:** Keep service role key secret! Never commit to git or expose in client-side code.

### 3. Set Up Monitoring

Monitor these metrics:
- Circuit breaker state
- Cache pending writes
- Database response time
- Failed connection attempts

Dashboard query:
```python
status = db.get_cache_status()
if status["circuit_breaker"]["state"] == "OPEN":
    # Alert: Database unavailable
```

### 4. Configure Backup

Supabase auto-backups daily, but for critical data:

1. Enable Point-in-Time Recovery (PITR)
2. Set up webhook notifications for trades
3. Export critical data to backup storage

---

## Migration from JSON

If you have existing data in `trade_log.json`:

### Option A: Manual Import

```python
from utils.db_client import DatabaseClient
import json

db = DatabaseClient()

# Load existing trades
with open('trade_log.json', 'r') as f:
    trades = json.load(f)

# Import each trade
for trade in trades:
    reasoning = {"legacy": True, "source": "trade_log.json"}
    db.log_trade_with_reasoning(trade, reasoning)
```

### Option B: Use Migration Script

```bash
python scripts/migrate_trades.py
```

(Migration script already exists in the project)

---

## Next Steps

1. **Configure real credentials** in `.env.adk`
2. **Run schema deployment** in Supabase dashboard
3. **Test connection** with test script
4. **Update dashboard.py** to use query layer
5. **Monitor cache status** during first runs

## Support

For issues:
1. Check [walkthrough.md](file:///C:/Users/BartPersoons/.gemini/antigravity/brain/044c2381-c556-4eb1-a0fa-dc7363c9ad77/walkthrough.md) for detailed implementation
2. Review [supabase_schema.sql](file:///c:/Users/BartPersoons/projects/Agent_trader/integrations/supabase_schema.sql) for schema
3. Run debug tests:
   ```bash
   python tests/test_supabase_connection.py
   python -m utils.db_client --test-connection
   ```
