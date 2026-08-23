-- HealthFlow — Migration 002: seed data + convenience view
-- Run after 001_init_schema.sql

-- Medicine catalog seed:
-- Load the deduped `name` column from the Kaggle "A-Z Medicine Dataset of India" CSV.
-- Example (run separately via psql \copy, not as raw SQL, since it needs the CSV file path):
--
--   \copy medicine_catalog(name) FROM 'az_medicine_dataset_india_names_deduped.csv' WITH (FORMAT csv, HEADER true)
--
-- Dedup + column extraction from the source CSV (name column only) can be done once with:
--   csvcut -c name az_medicine_dataset_india.csv | sort -u -f > az_medicine_dataset_india_names_deduped.csv
--
-- All seeded rows get status='active', added_by=NULL (distinguishes bulk-seed from doctor-added entries).

-- Convenience view: a doctor's remaining capacity per slot, source of truth for the
-- hourly reconciliation sweep described in the design doc (§6).
CREATE VIEW slot_availability AS
SELECT
  s.id            AS slot_id,
  s.doctor_id,
  s.date,
  s.slot_start,
  s.slot_end,
  s.capacity,
  s.capacity - COUNT(a.id) FILTER (
    WHERE a.status IN ('held', 'confirmed')
  ) AS true_remaining
FROM appointment_slots s
LEFT JOIN appointments a ON a.slot_id = s.id
GROUP BY s.id;

-- Convenience view: today's affected appointments for a half-day absence marking,
-- used by the admin attendance action to know exactly who to notify (design doc §4).
CREATE VIEW affected_by_attendance AS
SELECT
  a.id AS appointment_id,
  a.patient_id,
  a.doctor_id,
  s.date,
  s.slot_start,
  CASE WHEN s.slot_start < '13:00' THEN 'morning' ELSE 'afternoon' END AS shift
FROM appointments a
JOIN appointment_slots s ON s.id = a.slot_id
WHERE a.status IN ('held', 'confirmed');
