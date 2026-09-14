-- scripts/migrate_002_product_pricing.sql
--
-- Adds pricing to products, for counterfeit value-at-risk reporting.
-- Idempotent: safe to re-run.
--
--   unit_price   what the manufacturer sells the unit for (ex-factory /
--                trade). The revenue actually diverted per counterfeit
--                bottle, and the figure they already record.
--   retail_price shelf price — a different number owned by a different
--                party. Kept separate so exposure is never inflated by
--                retail margin.
--   currency     explicit. Silently mixing currencies is worse than
--                reporting no value at all.
--
-- Prices stay nullable: manufacturer uploads are always partial, and a
-- product without a price must still scan normally — it just doesn't
-- contribute to value-at-risk.

ALTER TABLE products ADD COLUMN IF NOT EXISTS unit_price   NUMERIC(12,2);
ALTER TABLE products ADD COLUMN IF NOT EXISTS retail_price NUMERIC(12,2);
ALTER TABLE products ADD COLUMN IF NOT EXISTS currency     VARCHAR(3) NOT NULL DEFAULT 'KES';