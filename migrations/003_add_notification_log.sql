-- 003_add_notification_log.sql
-- Append-only Log aller versendeten Benachrichtigungen

CREATE TABLE IF NOT EXISTS notification_log (
    id SERIAL PRIMARY KEY,
    notification_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_notification_log_notification_id ON notification_log(notification_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_sent_at ON notification_log(sent_at);
