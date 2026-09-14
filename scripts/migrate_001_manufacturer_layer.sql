-- scripts/migrate_001_manufacturer_layer.sql
--
-- Adds product/manufacturer context to scan_events.
-- Idempotent: safe to re-run.
--
-- The three new tables (manufacturers, products, product_serials) are
-- created by init_db() on boot — only pre-existing tables need altering here.

ALTER TABLE scan_events ADD COLUMN IF NOT EXISTS serial_result   VARCHAR;
ALTER TABLE scan_events ADD COLUMN IF NOT EXISTS manufacturer_id VARCHAR;
ALTER TABLE scan_events ADD COLUMN IF NOT EXISTS brand           VARCHAR;
ALTER TABLE scan_events ADD COLUMN IF NOT EXISTS category        VARCHAR;

CREATE INDEX IF NOT EXISTS ix_scan_events_manufacturer_id
    ON scan_events (manufacturer_id);

CREATE INDEX IF NOT EXISTS ix_scan_events_created_at
    ON scan_events (created_at);