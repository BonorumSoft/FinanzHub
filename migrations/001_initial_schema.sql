-- 001_initial_schema.sql
-- Initial schema: transactions, balances, networth_history, price_history

CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    transaction_id TEXT UNIQUE NOT NULL,
    account_id TEXT NOT NULL,
    booking_date DATE NOT NULL,
    value_date DATE,
    amount NUMERIC(12,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    description TEXT,
    counterparty_name TEXT,
    counterparty_iban TEXT,
    is_internal BOOLEAN DEFAULT FALSE,
    category TEXT,
    umlagefaehig TEXT DEFAULT 'unbekannt',
    property_id TEXT,
    match_status TEXT,
    imported_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_booking_date ON transactions(booking_date);
CREATE INDEX IF NOT EXISTS idx_transactions_account_id ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_counterparty_iban ON transactions(counterparty_iban);

CREATE TABLE IF NOT EXISTS balances (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL,
    balance NUMERIC(12,2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_balances_account_recorded ON balances(account_id, recorded_at);

CREATE TABLE IF NOT EXISTS networth_history (
    id SERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL UNIQUE,
    bank_total NUMERIC(12,2) NOT NULL,
    securities_total NUMERIC(12,2) NOT NULL,
    real_estate_equity NUMERIC(12,2) NOT NULL,
    net_worth NUMERIC(12,2) NOT NULL,
    net_worth_real NUMERIC(12,2),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS price_history (
    id SERIAL PRIMARY KEY,
    isin TEXT NOT NULL,
    ticker TEXT,
    price NUMERIC(12,4) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    price_eur NUMERIC(12,4),
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_history_isin_recorded ON price_history(isin, recorded_at);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW()
);
