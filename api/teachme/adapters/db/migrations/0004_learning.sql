CREATE TABLE part_progress (
  id              uuid PRIMARY KEY,
  user_id         text NOT NULL,
  subject_id      uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  part_id         uuid NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  outline_version int  NOT NULL,
  status          text NOT NULL,
  best_score      numeric(5, 2),
  rounds_used     int  NOT NULL DEFAULT 0,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, part_id)
);
CREATE INDEX part_progress_user_subject_idx ON part_progress(user_id, subject_id);

CREATE TABLE attempts (
  id          uuid PRIMARY KEY,
  user_id     text NOT NULL,
  part_id     uuid NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  language    text NOT NULL,
  round_no    int  NOT NULL DEFAULT 0,
  status      text NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX attempts_user_part_idx ON attempts(user_id, part_id);

CREATE TABLE attempt_questions (
  id               uuid PRIMARY KEY,
  attempt_id       uuid NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  question_id      uuid NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  round_no         int  NOT NULL,
  position         int  NOT NULL,
  answer_text      text,
  answer_choice    int,
  relevance_score  real,
  relevance_band   text,
  route            text,
  check_verdict    text,
  grade            text,
  rubric_covered   int[],
  missed_concepts  text[],
  feedback         text,
  rejections       int  NOT NULL DEFAULT 0,
  answered_at      timestamptz,
  UNIQUE (attempt_id, round_no, position)
);
CREATE INDEX attempt_questions_answered_idx ON attempt_questions(attempt_id, answered_at);

CREATE TABLE reexplanations (
  id          uuid PRIMARY KEY,
  attempt_id  uuid NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  round_no    int  NOT NULL,
  section_ids uuid[] NOT NULL,
  language    text NOT NULL,
  body        text NOT NULL,
  model       text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
