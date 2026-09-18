"""Vercel Python function entry. Routes for subjects, learning and progress mount here in stage 3."""

from __future__ import annotations

import os
import sys

# Vercel executes this file directly; make the sibling package importable without installation.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI  # noqa: E402

app = FastAPI(title="teach-me")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "teach-me"}
