-- 005_add_receipts.sql
-- Beleg-Inbox: KI-Extraktion aus Kassenbons / Rechnungen

CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Herkunft
    source_email TEXT NOT NULL,
    source_subject TEXT,
    received_at TIMESTAMP NOT NULL,

    -- Originaldatei
    original_filename TEXT NOT NULL,
    original_mimetype TEXT NOT NULL,
    original_size_bytes INTEGER,

    -- Verarbeiteter Beleg
    pdf_path TEXT,
    pdf_stored_at TIMESTAMP,

    -- KI-Extraktion (nullable, wenn Extraktion fehlschlägt)
    extracted_date DATE,
    extracted_amount NUMERIC(10,2),
    extracted_currency TEXT DEFAULT 'EUR',
    extracted_merchant TEXT,
    extracted_category TEXT,
    extracted_invoice_number TEXT,
    extracted_is_invoice INTEGER,         -- 0/1 (SQLite-Compat)
    extracted_is_payment_proof INTEGER,
    extracted_tax_amount NUMERIC(10,2),
    extracted_confidence REAL,            -- 0.0–1.0
    extraction_raw TEXT,                  -- JSON als TEXT
    extraction_model TEXT,

    -- Matching gegen Transaktion
    matched_transaction_id TEXT,
    match_confidence REAL,
    match_method TEXT,
    matched_at TIMESTAMP,

    -- Status
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    processed_at TIMESTAMP,

    -- Buchungsrelevanz
    steuerrelevant INTEGER DEFAULT 0,     -- 0/1
    notizen TEXT
);

CREATE INDEX IF NOT EXISTS idx_receipts_status ON receipts(status);
CREATE INDEX IF NOT EXISTS idx_receipts_received_at ON receipts(received_at);
CREATE INDEX IF NOT EXISTS idx_receipts_matched_tx ON receipts(matched_transaction_id);
CREATE INDEX IF NOT EXISTS idx_receipts_extracted_date ON receipts(extracted_date);

CREATE TABLE IF NOT EXISTS receipt_tags (
    receipt_id INTEGER REFERENCES receipts(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (receipt_id, tag)
);
