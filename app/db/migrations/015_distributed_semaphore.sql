-- Cross-process concurrency slots (e.g. cap parallel LLM calls from many pollers).
CREATE TABLE IF NOT EXISTS distributed_semaphore_holders (
    resource TEXT NOT NULL,
    slot INT NOT NULL,
    owner TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (resource, slot)
);

CREATE INDEX IF NOT EXISTS idx_distributed_semaphore_holders_resource
    ON distributed_semaphore_holders (resource);
