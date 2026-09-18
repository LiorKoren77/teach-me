-- subjects.gloss_frequency feeds domain.glossary.render.Frequency, a Literal of exactly these
-- three values: anything else fails to load as a Subject at all, so the database rejects it.
ALTER TABLE subjects
  ADD CONSTRAINT subjects_gloss_frequency_check
  CHECK (gloss_frequency IN ('first', 'every', 'never'));
