-- scripts/migrate_006_drink_types.sql
--
-- Widens the drink types the database accepts to the shared vocabulary in
-- drinks/drink_types.py. Every existing row uses one of the original four
-- types, all of which remain valid, so nothing is rewritten.
--
-- Safe to run more than once.

BEGIN;

ALTER TABLE drink_session_items
    DROP CONSTRAINT IF EXISTS ck_drink_session_items_drink_type;

ALTER TABLE drink_session_items
    ADD CONSTRAINT ck_drink_session_items_drink_type
    CHECK (drink_type IN (
        'beer', 'cider', 'wine', 'whisky', 'vodka', 'gin',
        'brandy', 'rum', 'liqueur', 'rtd', 'spirits', 'other'
    ));

COMMIT;