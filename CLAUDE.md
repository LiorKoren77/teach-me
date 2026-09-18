@AGENTS.md

# teach-me project notes

- Design spec: `docs/superpowers/specs/2026-09-17-teach-me-design.md`. Read it before
  changing architecture. Stages 1-4 are the deliverable; stage 5 is optional.
- Backend Python package is `teachme` under `api/`; the repo, npm package and Vercel
  project are `teach-me`.
- GitHub: this is a personal project under `LiorKoren77`. Never use the company
  `gh` account. For `gh` calls use `GH_TOKEN=$(gh auth token --user LiorKoren77)`.
  Repo-local git identity is already set to LiorKoren77.
- Stages 1 and 2 (ingestion, tutorial generation) are complete. Run `teachme --help`.
