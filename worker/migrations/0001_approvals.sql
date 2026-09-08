CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  payload_hash TEXT NOT NULL,
  expires_at INTEGER NOT NULL,
  decision_json TEXT NOT NULL,
  status TEXT NOT NULL,
  reminded INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  consumed_at INTEGER
);

CREATE INDEX IF NOT EXISTS approvals_pending
ON approvals(status, reminded, expires_at);
