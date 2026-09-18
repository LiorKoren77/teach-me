#!/usr/bin/env bash
# Backend for the Playwright e2e suite: the fake stack (no API keys needed) against the local
# Postgres *test* database, seeded with one small, published subject.
#
# Usage:
#   scripts/e2e-backend.sh          seed, then run uvicorn in the foreground (Playwright's
#                                   webServer command: it owns the process and stops it when the
#                                   run ends)
#   scripts/e2e-backend.sh seed     seed only, do not start the server
#
# Idempotent: re-running reuses the subject if it is already published, otherwise (re)creates
# it and carries it through ingest -> generate -> publish, using the source and outline already
# there where possible.
#
# Needs the Python venv the api/ package is installed into (editable, so PYTHONPATH is set to
# this worktree's api/ rather than wherever the venv's install points). Override with
# TEACHME_VENV if it lives somewhere other than the default sibling checkout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TEACHME_VENV="${TEACHME_VENV:-$HOME/liorkoren77/teach-me/.venv}"
TEACHME_BIN="$TEACHME_VENV/bin/teachme"
PYTHON_BIN="$TEACHME_VENV/bin/python"
UVICORN_BIN="$TEACHME_VENV/bin/uvicorn"

for bin in "$TEACHME_BIN" "$PYTHON_BIN" "$UVICORN_BIN"; do
  if [[ ! -x "$bin" ]]; then
    echo "error: $bin not found (set TEACHME_VENV to the venv api/ is installed into)" >&2
    exit 1
  fi
done

E2E_DIR="$ROOT_DIR/.e2e"
mkdir -p "$E2E_DIR/files" "$E2E_DIR/digest"

export PYTHONPATH="$ROOT_DIR/api${PYTHONPATH:+:$PYTHONPATH}"
export DATABASE_URL="${DATABASE_URL:-postgresql://teachme:teachme@localhost:5433/teachme_test}"
export LLM_PROVIDER=fake
export EMBEDDINGS_PROVIDER=fake
export RERANKER_PROVIDER=noop
export FILE_STORE=local
export JOB_RUNNER=inprocess
# Settings fields are local_files_dir / digest_dir (LOCAL_FILES_DIR / DIGEST_DIR as env names);
# temp, per-worktree, and gitignored, so a run never touches the real sources/ or digest/.
export LOCAL_FILES_DIR="$E2E_DIR/files"
export DIGEST_DIR="$E2E_DIR/digest"

SUBJECT_NAME="E2E Playwright Subject"
SUBJECT_LANGUAGES="he,en"
SUBJECT_ID_FILE="$ROOT_DIR/e2e/.subject-id"

log() { echo "[e2e-backend] $*"; }

seed() {
  log "applying migrations"
  "$TEACHME_BIN" migrate

  log "creating (or reusing) subject: $SUBJECT_NAME"
  "$TEACHME_BIN" subject create "$SUBJECT_NAME" --languages "$SUBJECT_LANGUAGES"

  local line state subject_id
  line="$("$TEACHME_BIN" subject list | grep -F "$SUBJECT_NAME [")"
  state="$(sed -E 's/.*\[([a-z]+)\].*/\1/' <<<"$line")"
  subject_id="$(sed -E 's/.*id=([0-9a-f-]+).*$/\1/' <<<"$line")"

  if [[ "$state" == "published" ]]; then
    log "subject already published (id=$subject_id), reusing"
  else
    if [[ -z "$("$TEACHME_BIN" source list --subject "$SUBJECT_NAME")" ]]; then
      log "ingesting a small generated PDF"
      "$PYTHON_BIN" -c "
from pathlib import Path
from tests.helpers import make_pdf

Path('$E2E_DIR/seed.pdf').write_bytes(make_pdf(2))
"
      "$TEACHME_BIN" ingest --subject "$SUBJECT_NAME" --yes "$E2E_DIR/seed.pdf"
    else
      log "source already ingested, skipping"
    fi

    log "generating tutorial content"
    "$TEACHME_BIN" generate --subject "$SUBJECT_NAME"

    log "publishing"
    "$TEACHME_BIN" publish --subject "$SUBJECT_NAME"
  fi

  mkdir -p "$(dirname "$SUBJECT_ID_FILE")"
  printf '%s' "$subject_id" >"$SUBJECT_ID_FILE"
  log "subject id $subject_id written to ${SUBJECT_ID_FILE#"$ROOT_DIR"/}"
}

seed

if [[ "${1:-}" == "seed" ]]; then
  exit 0
fi

log "starting the API on :8000"
cd "$ROOT_DIR"
exec "$UVICORN_BIN" index:app --app-dir api --port 8000
