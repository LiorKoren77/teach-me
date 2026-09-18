-- Learning loop tables. The text columns below feed StrEnums in teachme.domain.models: a value
-- outside the enum cannot be loaded back as a domain object at all, so the database rejects it,
-- the same way 0003 constrains subjects.gloss_frequency.

CREATE TABLE part_progress (
  id              uuid PRIMARY KEY,
  user_id         text NOT NULL,
  subject_id      uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  part_id         uuid NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  outline_version int  NOT NULL CHECK (outline_version >= 0),
  status          text NOT NULL CHECK (
                    status IN ('not_started', 'learning', 'quizzing', 'reinforcing', 'passed', 'stalled')
                  ),
  -- PartProgress.best_score is the best round score as a fraction of 1, never a percent
  best_score      numeric(5, 4) CHECK (best_score BETWEEN 0 AND 1),
  rounds_used     int  NOT NULL DEFAULT 0 CHECK (rounds_used >= 0),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, part_id)
);
CREATE INDEX part_progress_user_subject_idx ON part_progress(user_id, subject_id);
CREATE INDEX part_progress_part_idx         ON part_progress(part_id);
CREATE INDEX part_progress_subject_idx      ON part_progress(subject_id);

CREATE TABLE attempts (
  id          uuid PRIMARY KEY,
  user_id     text NOT NULL,
  part_id     uuid NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  language    text NOT NULL,
  round_no    int  NOT NULL DEFAULT 0 CHECK (round_no >= 0),  -- Attempt.round_no starts at 0 too
  status      text NOT NULL CHECK (status IN ('active', 'passed', 'failed')),
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX attempts_user_part_idx ON attempts(user_id, part_id);
CREATE INDEX attempts_part_idx      ON attempts(part_id);
-- The learning service resumes the active attempt and only starts a new one once the previous
-- attempt is finished; two active attempts on the same part would split a student's progress.
CREATE UNIQUE INDEX attempts_one_active_idx ON attempts (user_id, part_id) WHERE status = 'active';

CREATE TABLE attempt_questions (
  id               uuid PRIMARY KEY,
  attempt_id       uuid NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  question_id      uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  round_no         int  NOT NULL CHECK (round_no >= 0),
  position         int  NOT NULL CHECK (position >= 0),
  answer_text      text,
  answer_choice    int,
  relevance_score  real CHECK (relevance_score BETWEEN 0 AND 1),
  relevance_band   text CHECK (relevance_band IN ('junk', 'low', 'uncertain', 'high')),
  route            text CHECK (
                     route IN ('reject_junk', 'check', 'grader', 'reject_off_topic', 'code')
                   ),
  check_verdict    text,
  grade            text CHECK (grade IN ('correct', 'partial', 'incorrect', 'off_topic', 'junk')),
  rubric_covered   int[],
  missed_concepts  text[],
  feedback         text,
  rejections       int  NOT NULL DEFAULT 0 CHECK (rejections >= 0),
  answered_at      timestamptz,
  -- A rejected answer is still a submission that may have cost a relevance-check call, so the
  -- per-minute rate limit counts rejections as well as answers.
  last_rejected_at timestamptz,
  UNIQUE (attempt_id, round_no, position)
);
CREATE INDEX attempt_questions_question_idx ON attempt_questions(question_id);

CREATE TABLE reexplanations (
  id          uuid PRIMARY KEY,
  attempt_id  uuid NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  round_no    int  NOT NULL CHECK (round_no >= 0),
  section_ids uuid[] NOT NULL,
  language    text NOT NULL,
  body        text NOT NULL,
  model       text NOT NULL,
  -- the stream hit max_tokens: the text is kept, and the view can say it stops mid-thought
  truncated   boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reexplanations_attempt_round_idx ON reexplanations(attempt_id, round_no);
