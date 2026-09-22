-- scripts/migrate_009_real_catalogue.sql
--
-- Puts the real products behind the seeded barcodes, each under the company
-- that actually sells it. The old seed had made-up products (County Sweet
-- Red, Blue Moon Gin, Legend Brandy) and wrong makers (Kenya Cane under KWAL,
-- when it is an EABL brand).
--
-- Run once:  python scripts/run_sql.py scripts/migrate_009_real_catalogue.sql
-- One transaction: it applies fully or not at all. Safe to re-run.
--
-- Prices: unit_price is an ex-factory estimate, about 60 percent of the
-- Kenyan shelf price seen in September 2026 (retail_price). Where no shelf
-- price was found, retail_price is NULL and the earlier estimate stays.

CREATE TEMP TABLE catalogue_fix (
    gtin14       VARCHAR(14) PRIMARY KEY,
    maker        VARCHAR NOT NULL,   -- manufacturers.slug
    brand        VARCHAR NOT NULL,
    product_name VARCHAR NOT NULL,
    category     VARCHAR NOT NULL,
    volume_ml    INTEGER NOT NULL,
    unit_price   NUMERIC(12, 2) NOT NULL,
    retail_price NUMERIC(12, 2)
) ON COMMIT DROP;

INSERT INTO catalogue_fix VALUES
    -- Kenya Wine Agencies
    ('06160000000043', 'kwal', 'Kibao',           'Kibao Vodka 750ml',              'vodka',   750,  480,  800),
    ('06160000000050', 'kwal', 'Kibao',           'Kibao Vodka 250ml',              'vodka',   250,  170,  290),
    ('06160000000111', 'kwal', 'Kibao',           'Kibao Gin 750ml',                'gin',     750,  490,  820),
    ('06160000000067', 'kwal', 'Hunter''s Choice', 'Hunter''s Choice Whisky 750ml',  'whisky',  750,  800,  NULL),
    ('06160000000074', 'kwal', 'Hunter''s Choice', 'Hunter''s Choice Whisky 250ml',  'whisky',  250,  275,  NULL),
    ('06160000000104', 'kwal', 'County',          'County Brandy 750ml',            'brandy',  750,  470,  790),
    ('06160000000128', 'kwal', 'Viceroy',         'Viceroy Brandy 750ml',           'brandy',  750, 1230, 2050),
    ('06160000000081', 'kwal', 'Caprice',         'Caprice Sweet Red 750ml',        'wine',    750,  580,  NULL),
    ('06160000000098', 'kwal', 'Caprice',         'Caprice Sweet White 1L',         'wine',   1000,  690, 1149),
    ('06160000000371', 'kwal', 'Amarula',         'Amarula Cream 750ml',            'liqueur', 750, 1680, 2795),
    ('06160000000388', 'kwal', '4th Street',      '4th Street Sweet Red 750ml',     'wine',    750,  870, 1450),
    ('06160000000395', 'kwal', 'Heineken',        'Heineken Lager 500ml Can',       'beer',    500,  240,  400),
    -- East African Breweries (KBL and UDV Kenya)
    ('06160000000012', 'eabl', 'Kenya Cane',      'Kenya Cane Smooth 750ml',        'rum',     750,  500,  840),
    ('06160000000029', 'eabl', 'Kenya Cane',      'Kenya Cane Smooth 250ml',        'rum',     250,  190,  320),
    ('06160000000036', 'eabl', 'Kenya Cane',      'Kenya Cane Pineapple 750ml',     'rum',     750,  500,  840),
    ('06160000000135', 'eabl', 'Tusker',          'Tusker Lager 500ml',             'beer',    500,  180,  300),
    ('06160000000142', 'eabl', 'Tusker',          'Tusker Lite 500ml Can',          'beer',    500,  200,  340),
    ('06160000000159', 'eabl', 'Tusker',          'Tusker Malt 500ml',              'beer',    500,  210,  348),
    ('06160000000166', 'eabl', 'Tusker',          'Tusker Cider 500ml',             'cider',   500,  210,  350),
    ('06160000000173', 'eabl', 'White Cap',       'White Cap Lager 500ml',          'beer',    500,  180,  300),
    ('06160000000180', 'eabl', 'Pilsner',         'Pilsner Lager 500ml',            'beer',    500,  170,  290),
    ('06160000000197', 'eabl', 'Balozi',          'Balozi Lager 500ml',             'beer',    500,  180,  300),
    ('06160000000203', 'eabl', 'Guinness',        'Guinness Stout 500ml',           'beer',    500,  180,  300),
    ('06160000000210', 'eabl', 'Richot',          'Richot Brandy 750ml',            'brandy',  750,  960, 1600),
    ('06160000000227', 'eabl', 'Chrome',          'Chrome Vodka 750ml',             'vodka',   750,  590,  NULL),
    ('06160000000234', 'eabl', 'Gilbey''s',        'Gilbey''s Special Dry Gin 750ml', 'gin',     750, 1080, 1795),
    ('06160000000241', 'eabl', 'Bond 7',          'Bond 7 Whisky 750ml',            'whisky',  750,  920,  NULL),
    ('06160000000258', 'eabl', 'Smirnoff',        'Smirnoff Ice Guarana 330ml',     'rtd',     330,  165,  NULL),
    ('06160000000340', 'eabl', 'Johnnie Walker',  'Johnnie Walker Red Label 750ml', 'whisky',  750, 1500, 2500),
    -- Keroche Breweries
    ('06160000000265', 'keroche', 'Summit',       'Summit Lager 500ml',             'beer',    500,  170,  290),
    ('06160000000272', 'keroche', 'Summit',       'Summit Malt 330ml',              'beer',    330,  170,  290),
    -- London Distillers (Kenya)
    ('06160000000302', 'ldk', 'Kenya King',       'Kenya King Gin 750ml',           'gin',     750,  490,  NULL),
    ('06160000000319', 'ldk', 'Kenya King',       'Kenya King Gin 250ml',           'gin',     250,  200,  NULL),
    ('06160000000326', 'ldk', 'Napoleon',         'Napoleon Gold Brandy 750ml',     'brandy',  750,  450,  750),
    ('06160000000333', 'ldk', 'Napoleon',         'Napoleon Gold Brandy 250ml',     'brandy',  250,  180,  300),
    -- Imported, not sold by any maker on Limi
    ('06160000000357', 'imports', 'Jameson',      'Jameson Irish Whiskey 750ml',    'whisky',  750, 2010, 3350),
    ('06160000000364', 'imports', 'Absolut',      'Absolut Vodka 750ml',            'vodka',   750, 1620, 2695);

-- Stop at once, before anything is written, if a maker slug is missing.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM catalogue_fix f
        LEFT JOIN manufacturers m ON m.slug = f.maker
        WHERE m.id IS NULL
    ) THEN
        RAISE EXCEPTION 'catalogue_fix names a manufacturer slug that does not exist';
    END IF;
END $$;

-- 1. Drinks already logged from a VALID scan whose type came from the ledger
--    (it still matches the category the scan recorded) follow the new type.
--    Anything a person chose that differs, and every unverified scan, stays.
UPDATE drink_session_items AS i
SET drink_type = f.category
FROM scan_events AS s
JOIN catalogue_fix AS f ON f.gtin14 = s.gtin
WHERE i.scan_event_id = s.id
  AND s.combined_auth_status = 'verified'
  AND i.drink_type = s.category
  AND i.drink_type <> f.category;

-- 2. The ledger itself.
UPDATE products AS p
SET manufacturer_id = m.id,
    brand           = f.brand,
    product_name    = f.product_name,
    category        = f.category,
    volume_ml       = f.volume_ml,
    unit_price      = f.unit_price,
    retail_price    = f.retail_price,
    is_active       = TRUE
FROM catalogue_fix AS f
JOIN manufacturers AS m ON m.slug = f.maker
WHERE p.gtin14 = f.gtin14
  AND (p.manufacturer_id, p.brand, p.product_name, p.category, p.volume_ml,
       p.unit_price, p.retail_price, p.is_active)
      IS DISTINCT FROM
      (m.id, f.brand, f.product_name, f.category, f.volume_ml,
       f.unit_price, f.retail_price, TRUE);

-- 3. Two Keroche codes held products that don't exist in that form. Keroche's
--    real extra lines have no confirmed pack size yet, so these are switched
--    off: a scan of them now reads as a brand not on Limi yet.
UPDATE products
SET is_active = FALSE
WHERE gtin14 IN ('06160000000289', '06160000000296')
  AND is_active;

-- 4. The copies each past scan took, which manufacturer dashboards read.
--    A scan of Kenya Cane now counts for EABL, not KWAL.
UPDATE scan_events AS s
SET manufacturer_id = p.manufacturer_id,
    brand           = p.brand,
    category        = p.category
FROM products AS p
JOIN catalogue_fix AS f ON f.gtin14 = p.gtin14
WHERE s.gtin = p.gtin14
  AND (s.manufacturer_id, s.brand, s.category)
      IS DISTINCT FROM (p.manufacturer_id, p.brand, p.category);

-- 5. Consumer reports go to the company whose product was reported.
UPDATE bottle_reports AS r
SET manufacturer_id = p.manufacturer_id,
    brand           = p.brand
FROM products AS p
JOIN catalogue_fix AS f ON f.gtin14 = p.gtin14
WHERE r.gtin = p.gtin14
  AND (r.manufacturer_id, r.brand)
      IS DISTINCT FROM (p.manufacturer_id, p.brand);