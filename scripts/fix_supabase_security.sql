-- ============================================
-- Security Fix: Supabase Linter Vulnerabilities
-- ============================================
-- Fixes 7 findings:
--   6x security_definer_view (ERROR)
--   1x rls_disabled_in_public (ERROR)
--
-- Safe to run multiple times (idempotent).
-- Run this in the Supabase SQL Editor.
-- ============================================

BEGIN;

-- ─── Fix 1/7: active_trades_summary ────────────────────────────
CREATE OR REPLACE VIEW public.active_trades_summary
WITH (security_invoker = true) AS
SELECT
    ticker,
    COUNT(*) as open_positions,
    SUM(quantity * entry_price) as total_exposure,
    AVG(conviction) as avg_conviction,
    MAX(created_at) as latest_entry
FROM trades
WHERE status = 'OPEN'
GROUP BY ticker;

-- ─── Fix 2/7: analyst_performance_summary ──────────────────────
CREATE OR REPLACE VIEW public.analyst_performance_summary
WITH (security_invoker = true) AS
SELECT
    analyst,
    COUNT(*) as total_predictions,
    AVG(accuracy) as avg_accuracy,
    MIN(accuracy) as min_accuracy,
    MAX(accuracy) as max_accuracy,
    MAX(timestamp) as last_prediction
FROM agent_performance
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY analyst;

-- ─── Fix 3/7: trade_pnl_summary ───────────────────────────────
CREATE OR REPLACE VIEW public.trade_pnl_summary
WITH (security_invoker = true) AS
SELECT
    ticker,
    COUNT(*) as total_trades,
    COUNT(CASE WHEN status = 'CLOSED' AND pnl > 0 THEN 1 END) as winning_trades,
    COUNT(CASE WHEN status = 'CLOSED' AND pnl < 0 THEN 1 END) as losing_trades,
    SUM(pnl) as total_pnl,
    AVG(pnl) as avg_pnl,
    MAX(pnl) as max_profit,
    MIN(pnl) as max_loss
FROM trades
WHERE status = 'CLOSED'
GROUP BY ticker;

-- ─── Fix 4/7: recent_market_activity ──────────────────────────
CREATE OR REPLACE VIEW public.recent_market_activity
WITH (security_invoker = true) AS
SELECT
    ticker,
    snapshot_data->>'price' as current_price,
    snapshot_data->>'volume' as volume,
    timestamp
FROM market_snapshots
WHERE timestamp > NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC;

-- ─── Fix 5/7: swarm_dashboard ─────────────────────────────────
CREATE OR REPLACE VIEW public.swarm_dashboard
WITH (security_invoker = true) AS
SELECT
    agent_name AS "Agent",
    status AS "Status",
    last_pulse AS "Last Pulse",
    cycle_count AS "Cycles",
    CASE
        WHEN last_error IS NULL THEN 'None'
        ELSE LEFT(last_error, 100)
    END AS "Last Error",
    EXTRACT(EPOCH FROM (NOW() - last_pulse)) / 60 AS "Minutes Since Pulse"
FROM swarm_health
ORDER BY agent_name;

-- ─── Fix 6/7: cpo_priorities ──────────────────────────────────
CREATE OR REPLACE VIEW public.cpo_priorities
WITH (security_invoker = true) AS
SELECT
    id,
    priority,
    title,
    category,
    status,
    LEFT(description, 150) AS "Summary",
    created_at
FROM system_backlog
WHERE status IN ('PENDING', 'IN_PROGRESS')
ORDER BY priority DESC, created_at ASC
LIMIT 10;

-- ─── Fix 7/7: system_state RLS ────────────────────────────────
ALTER TABLE public.system_state ENABLE ROW LEVEL SECURITY;

-- Policy (only if not exists — Supabase errors on duplicate policy names)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'system_state'
        AND policyname = 'Enable all operations for authenticated users'
    ) THEN
        CREATE POLICY "Enable all operations for authenticated users" ON public.system_state
            FOR ALL
            TO authenticated
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

COMMIT;

-- ============================================
-- Verify: Re-run the Supabase linter after applying.
-- All 7 findings should be resolved.
-- ============================================
