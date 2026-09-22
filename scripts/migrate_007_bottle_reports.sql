-- scripts/migrate_007_bottle_reports.sql
--
-- Reports people make about a bottle they scanned, sent from the activity
-- centre. A report is one person's account of one bottle, never a claim
-- about a brand, so it is tied to a single scan event.
--
-- The facts a manufacturer needs are copied from the scan at report time,
-- so the manufacturer view reads this table alone and never joins back to
-- user-level scan rows.
--
-- run_sql.py applies the whole file as one transaction. Safe to run more
-- than once.

CREATE TABLE IF NOT EXISTS bottle_reports (
    id               VARCHAR PRIMARY KEY,
    user_id          VARCHAR NOT NULL,
    scan_event_id    VARCHAR NOT NULL REFERENCES scan_events (id),

    reason           VARCHAR NOT NULL,
    note             VARCHAR(280),

    -- Which wording of the consent line the person agreed to. Kept so it
    -- is always clear what they confirmed when they sent it.
    consent_version  VARCHAR NOT NULL,

    -- Copied from the scan event when the report is made.
    manufacturer_id  VARCHAR,
    gtin             VARCHAR(14),
    brand            VARCHAR,
    county           VARCHAR,
    scan_status      VARCHAR,
    scanned_at       TIMESTAMPTZ,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One report per person per scan.
    CONSTRAINT uq_bottle_reports_user_scan UNIQUE (user_id, scan_event_id),

    CONSTRAINT ck_bottle_reports_reason CHECK (reason IN (
        'taste_smell_wrong',
        'felt_unwell',
        'other'
    ))
);

-- Pirple Intelligence: a manufacturer's reports, newest first. Also what
-- the live feed polls against.
CREATE INDEX IF NOT EXISTS ix_bottle_reports_manufacturer_created
    ON bottle_reports (manufacturer_id, created_at DESC);

-- The daily cap: one person's reports, newest first.
CREATE INDEX IF NOT EXISTS ix_bottle_reports_user_created
    ON bottle_reports (user_id, created_at DESC);

-- The activity centre: one person's scans, newest first.
CREATE INDEX IF NOT EXISTS ix_scan_events_user_created
    ON scan_events (user_id, created_at DESC);