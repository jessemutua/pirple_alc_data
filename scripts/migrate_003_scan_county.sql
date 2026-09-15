-- scripts/migrate_003_scan_county.sql
--
-- Tags scans with the county they happened in, for the national map.
-- Idempotent: safe to re-run.
--
-- Nullable by design. A scan can legitimately have no county: no
-- coordinates were captured, the boundary file was not present when it was
-- recorded, or the point falls outside every boundary.

ALTER TABLE scan_events ADD COLUMN IF NOT EXISTS county VARCHAR;

CREATE INDEX IF NOT EXISTS ix_scan_events_county
    ON scan_events (county);

-- The shape almost every county query takes: one manufacturer, one period.
CREATE INDEX IF NOT EXISTS ix_scan_events_mfr_county_created
    ON scan_events (manufacturer_id, county, created_at);