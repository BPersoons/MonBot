-- ============================================
-- Supabase Database Schema for Agent Trader
-- ============================================
-- Run this script in your Supabase SQL Editor to create the required tables.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ===== Trades Table =====
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    conviction DECIMAL(5, 2),
    entry_price DECIMAL(15, 2),
    exit_price DECIMAL(15, 2),
    quantity DECIMAL(15, 8),
    pnl DECIMAL(15, 2),
    status VARCHAR(10) DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    risk_metrics JSONB,
    analyst_signals JSONB,
    reasoning_trace JSONB,  -- ENHANCED: Full ADK decision chain
    audited BOOLEAN DEFAULT FALSE,  -- Track if trade has been audited for performance
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_ticker_status ON trades(ticker, status);
CREATE INDEX IF NOT EXISTS idx_trades_audited ON trades(audited) WHERE status = 'CLOSED';

-- ===== Agent Performance Table =====
CREATE TABLE IF NOT EXISTS agent_performance (
    id BIGSERIAL PRIMARY KEY,
    analyst VARCHAR(50) NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    prediction DECIMAL(5, 2),
    actual_outcome DECIMAL(5, 2),
    accuracy DECIMAL(5, 4),
    metrics JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_performance_analyst ON agent_performance(analyst);
CREATE INDEX IF NOT EXISTS idx_performance_ticker ON agent_performance(ticker);
CREATE INDEX IF NOT EXISTS idx_performance_timestamp ON agent_performance(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_performance_analyst_ticker ON agent_performance(analyst, ticker);

-- ===== Market Snapshots Table =====
CREATE TABLE IF NOT EXISTS market_snapshots (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    snapshot_data JSONB NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON market_snapshots(ticker);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON market_snapshots(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_timestamp ON market_snapshots(ticker, timestamp DESC);

-- ===== System State Table =====
CREATE TABLE IF NOT EXISTS system_state (
    id BIGSERIAL PRIMARY KEY,
    key VARCHAR(100) UNIQUE NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index
CREATE INDEX IF NOT EXISTS idx_system_state_key ON system_state(key);

COMMENT ON TABLE system_state IS 'Global system configuration (active assets, system status, etc.)';

-- ===== Views for Dashboard Aggregations =====

-- Active trades summary
CREATE OR REPLACE VIEW active_trades_summary
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

-- Performance summary by analyst
CREATE OR REPLACE VIEW analyst_performance_summary
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

-- Trade P&L summary
CREATE OR REPLACE VIEW trade_pnl_summary
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

-- Recent market activity
CREATE OR REPLACE VIEW recent_market_activity
WITH (security_invoker = true) AS
SELECT
    ticker,
    snapshot_data->>'price' as current_price,
    snapshot_data->>'volume' as volume,
    timestamp
FROM market_snapshots
WHERE timestamp > NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC;

-- ===== Row Level Security =====
-- Enable RLS on all tables
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_performance ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_state ENABLE ROW LEVEL SECURITY;

-- Create policy for authenticated users (adjust as needed)
CREATE POLICY "Enable all operations for authenticated users" ON trades
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Enable all operations for authenticated users" ON agent_performance
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Enable all operations for authenticated users" ON market_snapshots
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

CREATE POLICY "Enable all operations for authenticated users" ON system_state
    FOR ALL
    TO authenticated
    USING (true)
    WITH CHECK (true);

-- ===== Functions for Common Operations =====

-- Function to calculate win rate for a ticker
CREATE OR REPLACE FUNCTION get_win_rate(ticker_symbol VARCHAR)
RETURNS DECIMAL AS $$
DECLARE
    total_closed INTEGER;
    winning_trades INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_closed
    FROM trades
    WHERE ticker = ticker_symbol AND status = 'CLOSED';
    
    IF total_closed = 0 THEN
        RETURN 0;
    END IF;
    
    SELECT COUNT(*) INTO winning_trades
    FROM trades
    WHERE ticker = ticker_symbol AND status = 'CLOSED' AND pnl > 0;
    
    RETURN (winning_trades::DECIMAL / total_closed::DECIMAL) * 100;
END;
$$ LANGUAGE plpgsql;

-- Function to get analyst reliability score
CREATE OR REPLACE FUNCTION get_analyst_reliability(analyst_name VARCHAR, days INTEGER DEFAULT 30)
RETURNS DECIMAL AS $$
BEGIN
    RETURN (
        SELECT AVG(accuracy)
        FROM agent_performance
        WHERE analyst = analyst_name
        AND timestamp > NOW() - (days || ' days')::INTERVAL
    );
END;
$$ LANGUAGE plpgsql;

-- ===== Insert Sample Data (Optional - for testing) =====
-- Uncomment to insert test records

-- INSERT INTO trades (ticker, action, conviction, entry_price, quantity, risk_metrics, analyst_signals)
-- VALUES (
--     'BTC/USDT',
--     'BUY',
--     2.5,
--     45000.00,
--     0.1,
--     '{"kelly_fraction": 0.15, "sharpe_ratio": 1.8}',
--     '{"technical": 0.75, "fundamental": 0.85, "sentiment": 0.90}'
-- );

COMMENT ON TABLE trades IS 'Trade execution history and open positions';
COMMENT ON TABLE agent_performance IS 'Analyst prediction accuracy tracking';
COMMENT ON TABLE market_snapshots IS 'Time-series market data for backtesting';
