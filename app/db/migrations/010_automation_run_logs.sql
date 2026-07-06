ALTER TABLE message_automation_runs
  ADD COLUMN IF NOT EXISTS duration_ms INTEGER,
  ADD COLUMN IF NOT EXISTS llm_duration_ms INTEGER,
  ADD COLUMN IF NOT EXISTS automation_trace_json JSONB,
  ADD COLUMN IF NOT EXISTS subject TEXT,
  ADD COLUMN IF NOT EXISTS from_address TEXT;

CREATE INDEX IF NOT EXISTS idx_automation_runs_account_created
  ON message_automation_runs (account, created_at DESC);
