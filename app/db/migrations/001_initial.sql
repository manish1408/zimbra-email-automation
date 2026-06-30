CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    zimbra_id TEXT NOT NULL,
    account TEXT NOT NULL,
    subject TEXT,
    from_address TEXT,
    to_addresses JSONB DEFAULT '[]'::jsonb,
    date TEXT,
    fragment TEXT,
    folder TEXT,
    size INTEGER,
    is_read BOOLEAN,
    body TEXT,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    analyzed_at TIMESTAMPTZ,
    UNIQUE (zimbra_id, account)
);

CREATE INDEX IF NOT EXISTS idx_messages_account_analyzed
    ON messages (account, analyzed_at);

CREATE INDEX IF NOT EXISTS idx_messages_account_date
    ON messages (account, date DESC);

CREATE TABLE IF NOT EXISTS mailbox_state (
    account TEXT PRIMARY KEY,
    last_seen_date TEXT,
    last_poll_at TIMESTAMPTZ,
    last_poll_new_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS message_actions (
    id BIGSERIAL PRIMARY KEY,
    zimbra_id TEXT NOT NULL,
    account TEXT NOT NULL,
    category TEXT,
    is_spam BOOLEAN DEFAULT FALSE,
    folder_path TEXT,
    forwarded_to TEXT,
    ack_sent_at TIMESTAMPTZ,
    draft_saved BOOLEAN DEFAULT FALSE,
    classification_json JSONB,
    error TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (zimbra_id, account)
);

CREATE INDEX IF NOT EXISTS idx_message_actions_account
    ON message_actions (account, processed_at DESC);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id BIGSERIAL PRIMARY KEY,
    account TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    dominant_intent TEXT,
    message_count INTEGER,
    report_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_account
    ON analysis_runs (account, created_at DESC);
