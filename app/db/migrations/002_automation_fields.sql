-- Extend message_actions with automation output fields
ALTER TABLE message_actions ADD COLUMN IF NOT EXISTS draft_reply_text TEXT;
ALTER TABLE message_actions ADD COLUMN IF NOT EXISTS ack_body_text TEXT;
ALTER TABLE message_actions ADD COLUMN IF NOT EXISTS automation_thread_id TEXT;
ALTER TABLE message_actions ADD COLUMN IF NOT EXISTS report_json JSONB;

CREATE TABLE IF NOT EXISTS message_automation_runs (
    id BIGSERIAL PRIMARY KEY,
    account TEXT NOT NULL,
    zimbra_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    dry_run BOOLEAN DEFAULT FALSE,
    classification_json JSONB,
    actions_json JSONB,
    draft_reply_text TEXT,
    ack_body_text TEXT,
    report_json JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_automation_runs_message
    ON message_automation_runs (account, zimbra_id, created_at DESC);
