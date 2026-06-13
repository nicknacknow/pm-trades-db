-- Migration 001: Extract condition_id from payload_json before dropping it.
--
-- Run this against the existing database before deploying the updated code.
-- The code change adds the column via CREATE TABLE IF NOT EXISTS, but for
-- existing rows the column will be empty until this migration runs.

ALTER TABLE trade_events ADD COLUMN IF NOT EXISTS condition_id TEXT NOT NULL DEFAULT '';

UPDATE trade_events
SET condition_id = COALESCE(payload_json->'trade'->>'condition_id', '')
WHERE condition_id = '';

-- Optional: once condition_id is populated, drop payload_json to save space.
-- ALTER TABLE trade_events DROP COLUMN payload_json;
