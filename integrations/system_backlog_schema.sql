-- ============================================
-- System Backlog Table for CPO Priorities
-- ============================================
-- Run this in Supabase SQL Editor alongside the main schema

CREATE TABLE IF NOT EXISTS system_backlog (
    id BIGSERIAL PRIMARY KEY,
    priority INTEGER NOT NULL CHECK (priority >= 1 AND priority <= 10),
    title VARCHAR(200) NOT NULL,
    description TEXT,
    category VARCHAR(50) NOT NULL CHECK (category IN ('PERFORMANCE', 'RELIABILITY', 'FEATURE', 'SECURITY', 'DATA')),
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'DEFERRED')),
    created_by VARCHAR(50) DEFAULT 'CPO',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for quick lookups
CREATE INDEX IF NOT EXISTS idx_backlog_priority ON system_backlog(priority DESC);
CREATE INDEX IF NOT EXISTS idx_backlog_status ON system_backlog(status);
CREATE INDEX IF NOT EXISTS idx_backlog_category ON system_backlog(category);

-- Enable RLS
ALTER TABLE system_backlog ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Enable all operations for service role" ON system_backlog
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

-- Dashboard View for top priorities
CREATE OR REPLACE VIEW cpo_priorities
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

-- Pre-seed with sample improvement items
INSERT INTO system_backlog (priority, title, description, category, status) VALUES
    (9, 'MEV Protection Layer', 'Implement MEV protection for on-chain trades to reduce sandwich attack exposure on Hyperliquid.', 'SECURITY', 'PENDING'),
    (8, 'Latency Optimization', 'Reduce average execution latency from 250ms to sub-100ms by implementing WebSocket feeds.', 'PERFORMANCE', 'IN_PROGRESS'),
    (7, 'Multi-Asset Correlation', 'Add cross-asset correlation analysis to avoid concentrated positions during market-wide moves.', 'FEATURE', 'PENDING'),
    (6, 'Backup Data Pipeline', 'Implement redundant data sources for price feeds in case primary API fails.', 'RELIABILITY', 'PENDING'),
    (5, 'Historical Backtest Engine', 'Build comprehensive backtesting engine with realistic slippage simulation.', 'DATA', 'PENDING')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE system_backlog IS 'CPO-managed system improvement priorities and technical debt tracker';
