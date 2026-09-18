-- Who changed what a subject teaches. Every admin write route records one row here, on the same
-- connection as the change it describes, so the trail cannot disagree with the data: an action
-- that was refused or rolled back leaves nothing behind.
--
-- No foreign keys, for the same reason llm_usage has none: a delete is exactly the action whose
-- record has to outlive its subject, and a cascade would erase the evidence with the row. The
-- ids are kept as plain uuids, and a listing joins nothing.
--
-- `detail` is whatever that action wants remembered - a filename, a media type, a version - and
-- is read by people, not by code.
CREATE TABLE admin_actions (
  id         uuid PRIMARY KEY,
  user_id    text NOT NULL,
  action     text NOT NULL,
  subject_id uuid,
  source_id  uuid,
  detail     jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- clock_timestamp(), not now(): now() is the transaction's start time, so two actions
  -- recorded in one transaction would tie and the trail would have no order to read it in.
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
-- The upload cap counts one admin's recent actions; the listing filters by subject.
CREATE INDEX admin_actions_user_idx    ON admin_actions(user_id, created_at DESC);
CREATE INDEX admin_actions_subject_idx ON admin_actions(subject_id);
