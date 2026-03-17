-- Create swarm_health table for agent visibility
CREATE TABLE IF NOT EXISTS swarm_health (
    agent_name TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'IDLE', -- IDLE, WORKING, COOLDOWN, ERROR
    current_task TEXT,
    current_reasoning_snippet TEXT,
    last_pulse TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    cycle_start_time TIMESTAMP WITH TIME ZONE,
    meta JSONB,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable Row Level Security
ALTER TABLE swarm_health ENABLE ROW LEVEL SECURITY;

-- Policy: Service role has full access (Agents writing data)
CREATE POLICY "Service role access" ON swarm_health
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- Policy: Public read access (Dashboard reading data)
CREATE POLICY "Public read access" ON swarm_health
    FOR SELECT TO anon
    USING (true);

-- Comment
COMMENT ON TABLE swarm_health IS 'Real-time status tracking for AI Agents';
