-- Migration 001: Extract condition_id and remove payload_json.
--
-- The current schema (no data) already includes condition_id and excludes
-- payload_json. This migration is only needed if restoring from an old
-- backup that still has payload_json.

ALTER TABLE trade_events ADD COLUMN IF NOT EXISTS condition_id TEXT NOT NULL DEFAULT '';

UPDATE trade_events
SET condition_id = COALESCE(payload_json->'trade'->>'condition_id', '')
WHERE condition_id = '';

ALTER TABLE trade_events DROP COLUMN IF EXISTS payload_json;

CREATE INDEX IF NOT EXISTS idx_trade_events_condition_id
    ON trade_events (condition_id);
