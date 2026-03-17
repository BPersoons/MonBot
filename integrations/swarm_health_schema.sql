-- ============================================
-- Swarm Health Table for Agent Monitoring
-- ============================================
-- Run this in Supabase SQL Editor alongside the main schema

CREATE TABLE IF NOT EXISTS swarm_health (
    id BIGSERIAL PRIMARY KEY,
    agent_name VARCHAR(50) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('ACTIVE', 'IDLE', 'ERROR', 'STARTING')),
    last_pulse TIMESTAMPTZ DEFAULT NOW(),
    cycle_count INTEGER DEFAULT 0,
    last_error TEXT,
    metadata JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for quick lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_swarm_health_agent ON swarm_health(agent_name);
CREATE INDEX IF NOT EXISTS idx_swarm_health_status ON swarm_health(status);

-- Dashboard View
CREATE OR REPLACE VIEW swarm_dashboard
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

-- Enable RLS
ALTER TABLE swarm_health ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Enable all operations for service role" ON swarm_health
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

COMMENT ON TABLE swarm_health IS 'Real-time health status for all agents in the trading swarm';
