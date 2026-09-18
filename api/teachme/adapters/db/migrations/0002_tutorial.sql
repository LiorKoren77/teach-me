CREATE TABLE outlines (
  id         uuid PRIMARY KEY,
  subject_id uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  version    int  NOT NULL,
  model      text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (subject_id, version)
);

CREATE TABLE parts (
  id         uuid PRIMARY KEY,
  outline_id uuid NOT NULL REFERENCES outlines(id) ON DELETE CASCADE,
  position   int  NOT NULL,
  title      text NOT NULL,
  page_start int  NOT NULL,
  page_end   int  NOT NULL,
  UNIQUE (outline_id, position)
);

CREATE TABLE sections (
  id         uuid PRIMARY KEY,
  part_id    uuid NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  position   int  NOT NULL,
  title      text NOT NULL,
  page_start int  NOT NULL,
  page_end   int  NOT NULL,
  UNIQUE (part_id, position)
);

CREATE TABLE glossary_terms (
  id          uuid PRIMARY KEY,
  outline_id  uuid NOT NULL REFERENCES outlines(id) ON DELETE CASCADE,
  slug        text NOT NULL,
  source_term text NOT NULL,
  definition  text NOT NULL,
  pages       int[] NOT NULL,
  UNIQUE (outline_id, slug)
);

CREATE TABLE glossary_translations (
  term_id  uuid NOT NULL REFERENCES glossary_terms(id) ON DELETE CASCADE,
  language text NOT NULL,
  term     text NOT NULL,
  PRIMARY KEY (term_id, language)
);

CREATE TABLE part_content (
  part_id    uuid NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
  language   text NOT NULL,
  title      text NOT NULL,
  body       text NOT NULL,
  key_points text[] NOT NULL,
  status     text NOT NULL,
  model      text NOT NULL,
  error      text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (part_id, language)
);

CREATE TABLE section_content (
  section_id uuid NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
  language   text NOT NULL,
  title      text NOT NULL,
  summary    text NOT NULL,
  PRIMARY KEY (section_id, language)
);

CREATE TABLE questions (
  id              uuid PRIMARY KEY,
  section_id      uuid NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
  language        text NOT NULL,
  kind            text NOT NULL,
  prompt          text NOT NULL,
  expected_answer text NOT NULL,
  rubric          text[] NOT NULL,
  key_terms       text[] NOT NULL,
  exact_values    text[] NOT NULL,
  choices         text[],
  correct_choice  int,
  position        int NOT NULL
);
CREATE INDEX questions_section_language_idx ON questions(section_id, language);
