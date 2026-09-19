-- Retiring a code is a fact about the seal, so it lives on the serial, not
-- on a scan. One way only: there is no un-retire.
ALTER TABLE product_serials
  ADD COLUMN IF NOT EXISTS retired_at   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS retired_by   TEXT,
  ADD COLUMN IF NOT EXISTS retired_lat  DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS retired_lng  DOUBLE PRECISION;

-- "How many codes has this manufacturer had retired, and when" is a
-- question the dashboard will ask.
CREATE INDEX IF NOT EXISTS ix_product_serials_retired_at
  ON product_serials (retired_at DESC);

-- Everything the next version of the algorithm will need, captured on every
-- scan from today whether or not anything reads it yet. Without this there
-- is no way to measure real baselines later, and every threshold stays a
-- guess.
ALTER TABLE scan_events
  ADD COLUMN IF NOT EXISTS scan_features JSONB;