-- Migration: Schema cleanup
-- 1. Separate GA4 measurement ID (G-XXX) from GA4 property ID (numeric) and GA3 UA ID
-- 2. Rename gads_dc_label → gads_appt_label
-- 3. Drop deprecated ga4_id (absorbed into ga4_measurement_id)
--
-- Run:
--   docker exec -i supabase_db_supabasenoir psql -U postgres -d postgres < migrations/20260427_schema_cleanup.sql

BEGIN;

-- ── Add new columns ────────────────────────────────────────────────────────────

ALTER TABLE locations
  ADD COLUMN IF NOT EXISTS ga4_property_id    text,   -- numeric GA4 property ID
  ADD COLUMN IF NOT EXISTS ga3_measurement_id text;   -- legacy UA-XXXXX-X tracking ID

-- ── Backfill ga4_measurement_id from ga4_id (G-XXXXXXXXXX values only) ────────

UPDATE locations
SET ga4_measurement_id = ga4_id
WHERE ga4_id LIKE 'G-%'
  AND ga4_measurement_id IS NULL;

-- ── Backfill ga3_measurement_id from ga4_id (UA-XXXXX-X values only) ──────────

UPDATE locations
SET ga3_measurement_id = ga4_id
WHERE ga4_id LIKE 'UA-%'
  AND ga3_measurement_id IS NULL;

-- ── Rename gads_dc_label → gads_appt_label ────────────────────────────────────

ALTER TABLE locations RENAME COLUMN gads_dc_label TO gads_appt_label;

-- ── Drop ga4_id (absorbed by ga4_measurement_id / ga3_measurement_id) ─────────
-- 381 rows had GTM container IDs stored here — those are discarded.
-- 3 valid G- values were migrated to ga4_measurement_id above.

ALTER TABLE locations DROP COLUMN ga4_id;

COMMIT;

-- ── Verification ───────────────────────────────────────────────────────────────
-- Run after migration to confirm expected counts:
--
-- SELECT
--   COUNT(*) FILTER (WHERE ga4_measurement_id IS NOT NULL)  AS ga4_meas_set,
--   COUNT(*) FILTER (WHERE ga4_measurement_id LIKE 'G-%')   AS ga4_meas_valid,
--   COUNT(*) FILTER (WHERE ga3_measurement_id IS NOT NULL)  AS ga3_set,
--   COUNT(*) FILTER (WHERE ga4_property_id    IS NOT NULL)  AS ga4_prop_set,
--   COUNT(*) FILTER (WHERE gads_appt_label    IS NOT NULL)  AS appt_label_set
-- FROM locations;
--
-- Expected: ga4_meas_set=4 (3 migrated + 1 existing), ga4_meas_valid=4,
--           ga3_set=0, ga4_prop_set=0, appt_label_set=540
