-- 002_add_events.sql
-- Event-Log: erkannte Ereignisse mit Idempotenz auf (event_type, entity_id, period)

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_id TEXT,
    period TEXT,
    details JSONB,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    notified BOOLEAN DEFAULT FALSE,
    UNIQUE(event_type, entity_id, period)
);

CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_detected_at ON events(detected_at);
