ALTER TABLE agent_training
    ADD COLUMN IF NOT EXISTS draft_reply_content TEXT NOT NULL DEFAULT '';
