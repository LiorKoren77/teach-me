CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE subjects (
  id                      uuid PRIMARY KEY,
  name                    text NOT NULL UNIQUE,
  state                   text NOT NULL DEFAULT 'draft',
  languages               text[] NOT NULL,
  pass_threshold          int  NOT NULL DEFAULT 50,
  max_rounds              int  NOT NULL DEFAULT 3,
  questions_per_round     int  NOT NULL DEFAULT 5,
  bank_size_per_part      int  NOT NULL DEFAULT 25,
  gloss_frequency         text NOT NULL DEFAULT 'first',
  current_outline_version int,
  created_by              text,
  created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sources (
  id                uuid PRIMARY KEY,
  subject_id        uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  filename          text NOT NULL,
  media_type        text NOT NULL,
  file_key          text NOT NULL,
  size              bigint NOT NULL,
  status            text NOT NULL,
  resume_status     text,
  error             text,
  page_count        int,
  vision_pages      int,
  detected_language text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sources_subject_idx ON sources(subject_id);

CREATE TABLE source_pages (
  source_id      uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  page_index     int  NOT NULL,
  printed_number text,
  text           text NOT NULL,
  PRIMARY KEY (source_id, page_index)
);

CREATE TABLE source_figures (
  source_id   uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  page_index  int  NOT NULL,
  ordinal     int  NOT NULL,
  kind        text NOT NULL,
  caption     text NOT NULL,
  description text NOT NULL,
  PRIMARY KEY (source_id, page_index, ordinal)
);

CREATE TABLE chunks (
  id              uuid PRIMARY KEY,
  source_id       uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  subject_id      uuid NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  context         text NOT NULL,
  text            text NOT NULL,
  page_start      int  NOT NULL,
  page_end        int  NOT NULL,
  embedding       vector(1024) NOT NULL,
  embedding_model text NOT NULL,
  tokens          tsvector NOT NULL
);
CREATE INDEX chunks_subject_idx   ON chunks(subject_id);
CREATE INDEX chunks_source_idx    ON chunks(source_id);
CREATE INDEX chunks_tokens_idx    ON chunks USING gin(tokens);
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE jobs (
  id         uuid PRIMARY KEY,
  kind       text NOT NULL,
  payload    jsonb NOT NULL,
  status     text NOT NULL,
  attempts   int  NOT NULL DEFAULT 0,
  error      text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE llm_usage (
  id                 uuid PRIMARY KEY,
  created_at         timestamptz NOT NULL DEFAULT now(),
  purpose            text NOT NULL,
  provider           text NOT NULL,
  model              text NOT NULL,
  input_tokens       int  NOT NULL,
  output_tokens      int  NOT NULL,
  cache_read_tokens  int  NOT NULL DEFAULT 0,
  cache_write_tokens int  NOT NULL DEFAULT 0,
  cost_usd           numeric(12, 6) NOT NULL,
  latency_ms         int  NOT NULL,
  user_id            text,
  subject_id         uuid,
  source_id          uuid,
  attempt_id         uuid
);
CREATE INDEX llm_usage_subject_idx ON llm_usage(subject_id);
CREATE INDEX llm_usage_source_idx  ON llm_usage(source_id);
