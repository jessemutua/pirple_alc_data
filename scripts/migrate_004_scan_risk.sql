-- The consumer verdict and the manufacturer's view of a scan are different
-- questions with different costs of being wrong, so the score is stored
-- rather than derived from the status. A scan can read clean to the person
-- holding the bottle and still belong in KWAL's review queue.

ALTER TABLE scan_events
  ADD COLUMN IF NOT EXISTS risk_score DOUBLE PRECISION NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS risk_reasons JSONB;

-- The review queue is "everything above a threshold, newest first".
CREATE INDEX IF NOT EXISTS ix_scan_events_risk_score
  ON scan_events (risk_score DESC, created_at DESC);