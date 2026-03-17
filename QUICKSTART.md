# Quick Start Guide - ADK Trading System

## 🚀 Getting Started in 5 Minutes

### Prerequisites
- Python 3.11+
- Docker Desktop (for Redis)
- Git

### Step 1: Clone & Install

```bash
cd c:\Users\BartPersoons\projects\Agent_trader

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy template
copy .env.adk.example .env

# Edit .env - minimum required:
# REDIS_HOST=localhost
# REDIS_PORT=6379
# GOOGLE_API_KEY=your_key_here
```

### Step 3: Start Redis

```bash
# Start Redis via Docker
docker-compose up -d redis

# Verify
docker-compose ps
```

### Step 4: Migrate State (First Time Only)

```bash
# Migrate existing data to StateStore
python scripts/migrate_state.py
```

### Step 5: Run Demo

```bash
# Test with demo (simulated data)
python demo_adk.py
```

Expected output:
- ✓ Council request created
- ✓ 3 analyst votes collected
- ⚠️ Conflict detected (Technical vs Sentiment)
- ✓ Synthesis report generated
- ✓ Trade proposal created

### Step 6: Run End-to-End Test

```bash
# Full trading cycle test
python tests/test_adk_e2e.py
```

This will:
1. Create council request
2. Invoke all 3 analysts
3. ProjectLead processes votes
4. Detect conflicts if any
5. Risk Manager validates
6. Execute trade (paper)

### Step 7: Start Full Application

```bash
# Run ADK application
python adk_app.py
```

The app will:
- Initialize all agents
- Run continuous trading cycles (configured interval)
- Log all activity to `adk_heartbeat.log`

### Step 8: Monitor Dashboard

```bash
# In separate terminal
streamlit run dashboard.py
```

Visit `http://localhost:8501` to see real-time activity.

---

## 🐋 Docker Deployment (Production)

```bash
# Build and start full stack
docker-compose up --build

# Services:
# - redis (StateStore)
# - db (PostgreSQL - alternative to Supabase)
# - app (ADK trading system)
# - dashboard (Streamlit UI)
```

---

## 🔍 Debugging

### Check StateStore

```bash
python scripts/inspect_state.py
```

Shows all keys and values in Redis.

### Check Logs

```bash
# Application logs
tail -f adk_heartbeat.log

# Docker logs
docker-compose logs -f app
```

### Verify Connections

```python
# Test StateManager
python -c "from core.state_manager import StateManager; sm = StateManager(); print(sm.get_system_status())"

# Test Supabase
python -c "from integrations.supabase_client import SupabaseClient; c = SupabaseClient(); print(c.is_available())"
```

---

## 📝 Common Issues

### Redis Connection Refused

```bash
# Start Redis
docker-compose up -d redis

# Or install locally
# Windows: https://github.com/microsoftarchive/redis/releases
```

### Google API Key Missing

```bash
# Add to .env
GOOGLE_API_KEY=your_gemini_api_key_here
```

Get key from: https://aistudio.google.com/app/apikey

### Import Errors

```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

---

## 🎯 Next Steps

1. **Test with Real Data**: Replace mock analysts with actual exchange connections
2. **Deploy to Cloud**: Use `docker-compose.yml` for Google Cloud Run
3. **Enable Supabase**: Create project and run `integrations/supabase_schema.sql`
4. **Customize Weights**: Adjust agent weights in StateStore based on performance

---

## 📚 Documentation

- [README_ADK.md](README_ADK.md) - Complete migration guide
- [walkthrough.md](.gemini/antigravity/brain/.../walkthrough.md) - Detailed implementation walkthrough
- [task.md](.gemini/antigravity/brain/.../task.md) - Task breakdown

---

**Status**: ✅ Production Ready for Paper Trading

**Migration Progress**: 90% Complete (Phases 1-3 done)
