# teach-me

Turns textbook material into a guided tutorial with an assessment dialog.
An admin ingests PDFs for a subject; the system digests them, teaches each part
in the student's chosen language (Hebrew, English or Portuguese), asks
questions, grades answers, re-explains weak sections and tracks progress.

- Frontend: Next.js (App Router), Clerk, Tailwind
- Backend: Python FastAPI under `api/`, Claude via the Anthropic SDK, Voyage
  embeddings, Postgres with pgvector
- Design: `docs/superpowers/specs/2026-09-17-teach-me-design.md`
