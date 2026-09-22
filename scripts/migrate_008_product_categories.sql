-- scripts/migrate_008_product_categories.sql
--
-- Gives every spirit in the catalogue its real type, and Tusker Cider its
-- own. A valid scan logs as the ledger's type, so a vague "spirits" here
-- showed up as "Spirits" in people's logs and drink-type charts.
--
-- Run once:  python scripts/run_sql.py scripts/migrate_008_product_categories.sql
-- The runner wraps the file in one transaction, so it applies fully or not
-- at all. Re-running changes nothing: every update skips rows already fixed.

CREATE TEMP TABLE category_fix (
    gtin14   VARCHAR(14) PRIMARY KEY,
    category VARCHAR NOT NULL
) ON COMMIT DROP;

INSERT INTO category_fix (gtin14, category) VALUES
    -- KWAL
    ('06160000000012', 'rum'),      -- Kenya Cane Original 750ml
    ('06160000000029', 'rum'),      -- Kenya Cane Original 250ml
    ('06160000000036', 'rum'),      -- Kenya Cane Coconut 750ml
    ('06160000000043', 'vodka'),    -- Kibao Vodka 750ml
    ('06160000000050', 'vodka'),    -- Kibao Vodka 250ml
    ('06160000000067', 'whisky'),   -- Hunter's Choice Whisky 750ml
    ('06160000000074', 'whisky'),   -- Hunter's Choice Whisky 250ml
    ('06160000000128', 'brandy'),   -- Viceroy Brandy 750ml
    -- EABL
    ('06160000000166', 'cider'),    -- Tusker Cider 500ml
    ('06160000000227', 'vodka'),    -- Chrome Vodka 750ml
    ('06160000000234', 'gin'),      -- Gilbey's Gin 750ml
    ('06160000000241', 'whisky'),   -- Bond 7 Whisky 750ml
    -- Keroche
    ('06160000000289', 'vodka'),    -- Viena Ice Vodka 750ml
    -- London Distillers
    ('06160000000302', 'vodka'),    -- Kenya King Vodka 750ml
    ('06160000000319', 'gin'),      -- Blue Moon Gin 750ml
    ('06160000000326', 'brandy'),   -- Napoleon Brandy 750ml
    ('06160000000333', 'brandy'),   -- Legend Brandy 750ml
    -- Imports
    ('06160000000340', 'whisky'),   -- Johnnie Walker Red Label 750ml
    ('06160000000357', 'whisky'),   -- Jameson Irish Whiskey 750ml
    ('06160000000364', 'vodka'),    -- Absolut Vodka 750ml
    ('06160000000371', 'liqueur');  -- Amarula Cream 750ml

-- 1. The ledger itself. Every scan from now on picks up the new type.
UPDATE products AS p
SET category = f.category
FROM category_fix AS f
WHERE p.gtin14 = f.gtin14
  AND p.category IS DISTINCT FROM f.category;

-- 2. The copy each past scan took at the time, which manufacturer reporting
--    groups by. Every past scan of these products, whatever its verdict.
UPDATE scan_events AS s
SET category = f.category
FROM category_fix AS f
WHERE s.gtin = f.gtin14
  AND s.category IS DISTINCT FROM f.category;

-- 3. Drinks already logged from a VALID scan of these products. Only the
--    old vague types move ("spirits", and "rtd" for Tusker Cider). A more
--    specific type someone chose, and every drink from an unverified scan,
--    stays exactly as it was logged.
UPDATE drink_session_items AS i
SET drink_type = f.category
FROM scan_events AS s
JOIN category_fix AS f ON f.gtin14 = s.gtin
WHERE i.scan_event_id = s.id
  AND s.combined_auth_status = 'verified'
  AND i.drink_type IN ('spirits', 'rtd')
  AND i.drink_type <> f.category;