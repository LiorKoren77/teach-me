-- What a job decided, for a redelivery of the same message to reuse. `generate_subject` records
-- the outline version its run resolved here, so the second delivery of an at-least-once queue
-- fans its part units out against that version instead of creating a second one. Null means the
-- job has not got that far yet, which is what every existing row is.
ALTER TABLE jobs ADD COLUMN result jsonb;
