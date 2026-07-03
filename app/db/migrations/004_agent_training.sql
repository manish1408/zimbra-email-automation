-- Global agent training text (singleton row id=1)
CREATE TABLE IF NOT EXISTS agent_training (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    content TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
