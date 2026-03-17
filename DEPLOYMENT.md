# ADK Migration - Deployment Checklist

## 🎯 Pre-Deployment Checklist

### Environment Setup
- [ ] `.env` file created from `.env.adk.example`
- [ ] `GOOGLE_API_KEY` configured
- [ ] `REDIS_HOST` and `REDIS_PORT` configured
- [ ] `SUPABASE_URL` and `SUPABASE_KEY` configured (if using Supabase)
- [ ] Exchange API keys configured (BINANCE, KRAKEN)

### Infrastructure
- [ ] Redis running (`docker-compose up -d redis`)
- [ ] Supabase project created (or local PostgreSQL)
- [ ] Database schema applied (`integrations/supabase_schema.sql`)
- [ ] Docker images built (`docker-compose build`)

### State Migration
- [ ] Backup of existing JSON files created
- [ ] `python scripts/migrate_state.py` executed successfully
- [ ] `python scripts/migrate_trades.py` executed successfully (if trade history exists)
- [ ] State verified with `python scripts/inspect_state.py`

### Testing
- [ ] Integration tests passed (`pytest tests/test_integration.py`)
- [ ] Scenario tests passed (`pytest tests/test_scenarios.py`)
- [ ] End-to-end test passed (`python tests/test_adk_e2e.py`)
- [ ] Final verification passed (`python tests/final_verification.py`)

---

## 🚀 Deployment Options

### Option 1: Local Development

```bash
# Start infrastructure
docker-compose up -d redis

# Run application
python adk_app.py

# In separate terminal, run dashboard
streamlit run dashboard.py
```

### Option 2: Full Docker Stack

```bash
# Start all services
docker-compose up --build

# Services running:
# - redis:6379 (StateStore)
# - db:5432 (PostgreSQL)
# - app (ADK trading system)
# - dashboard:8501 (Streamlit UI)
```

### Option 3: Cloud Deployment (Google Cloud Run)

```bash
# Build and push image
docker build -t gcr.io/[PROJECT-ID]/adk-trader .
docker push gcr.io/[PROJECT-ID]/adk-trader

# Deploy to Cloud Run
gcloud run deploy adk-trader \
  --image gcr.io/[PROJECT-ID]/adk-trader \
  --platform managed \
  --region us-central1 \
  --set-env-vars="GOOGLE_API_KEY=[KEY],REDIS_HOST=[HOST],..."
```

---

## 📊 Monitoring & Operations

### Health Checks

```bash
# Check system status
python -c "from core.state_manager import StateManager; sm = StateManager(); print(sm.get_system_status())"

# Check StateStore
python scripts/inspect_state.py

# Check logs
tail -f adk_heartbeat.log

# Check Docker logs
docker-compose logs -f app
```

### Dashboard Access
- **Local**: http://localhost:8501
- **Docker**: http://localhost:8501
- **Cloud**: https://[your-url].run.app

### Kill Switch
- **Dashboard**: Click "Pause System" button
- **CLI**: `python -c "from core.state_manager import StateManager; StateManager().set_system_status('PAUSED')"`
- **Redis**: `redis-cli SET system_status PAUSED`

### Resume Trading
- **Dashboard**: Click "Resume System" button
- **CLI**: `python -c "from core.state_manager import StateManager; StateManager().set_system_status('ACTIVE')"`

---

## 🔧 Troubleshooting

### Redis Connection Issues
```bash
# Check if Redis is running
docker-compose ps redis

# Restart Redis
docker-compose restart redis

# Test connection
redis-cli ping
```

### Supabase Connection Issues
```bash
# Test connection
python -c "from integrations.supabase_client import SupabaseClient; print(SupabaseClient().is_available())"

# Re-apply schema
psql -h [SUPABASE_HOST] -U postgres -d postgres -f integrations/supabase_schema.sql
```

### Agent Errors
```bash
# Check agent initialization
python -c "from agents_adk.project_lead_adk import ProjectLeadAgent; from core.state_manager import StateManager; ProjectLeadAgent(StateManager())"

# Run demo to test agents
python demo_adk.py
```

### Dashboard Not Updating
```bash
# Check StateStore connection in dashboard
# Restart dashboard
streamlit run dashboard.py --server.port 8501
```

---

## 📝 Maintenance

### Daily
- Monitor logs for errors
- Check system status in dashboard
- Verify active trades in Supabase

### Weekly
- Review agent performance metrics
- Adjust agent weights if needed
- Backup StateStore data (`redis-cli SAVE`)
- Review synthesis reports for conflicts

### Monthly
- Update dependencies (`pip install -r requirements.txt --upgrade`)
- Review and optimize agent strategies
- Analyze trade performance
- Update documentation

---

## 🔐 Security

### Production Checklist
- [ ] Environment variables stored securely (not in code)
- [ ] API keys rotated regularly
- [ ] Redis password configured (`REDIS_PASSWORD`)
- [ ] Supabase RLS policies enabled
- [ ] Docker containers running as non-root user
- [ ] HTTPS enabled for dashboard (if public)
- [ ] Firewall rules configured (only necessary ports open)

---

## 📚 Documentation

### Key Files
- **README_ADK.md**: Complete migration guide
- **QUICKSTART.md**: 5-minute setup guide
- **walkthrough.md**: Detailed implementation walkthrough
- **task.md**: Task breakdown and progress
- **SPECIFICATION.md**: Original system specification

### Support
- Check implementation plan for architecture decisions
- Review walkthrough for code examples
- Run `python scripts/inspect_state.py` for current state
- Check logs in `adk_heartbeat.log`

---

## ✅ Post-Deployment Verification

After deployment, verify:

1. **System Status**: Dashboard shows "ACTIVE"
2. **Agents**: All 6 agents initialized without errors
3. **StateStore**: Data persisting correctly
4. **Trading Cycle**: At least one complete cycle executed
5. **Logs**: No critical errors in `adk_heartbeat.log`
6. **Dashboard**: Real-time updates visible
7. **Supabase**: Trades being logged (if applicable)

---

## 🎉 Success Criteria

The ADK migration is considered successful when:

✅ All tests passing (integration, scenarios, e2e, final verification)  
✅ System running for 24+ hours without crashes  
✅ Debate logic preserved (conflicts detected, synthesis generated)  
✅ StateStore persisting data correctly  
✅ Dashboard displaying real-time data  
✅ Trades logged to Supabase  
✅ Kill switch functional  
✅ Docker deployment working  

---

**Migration Status**: ✅ Complete  
**Production Ready**: ✅ Yes (Paper Trading)  
**Last Updated**: 2026-02-03
