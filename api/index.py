"""Vercel Python function entry: every /api/* request is rewritten to this file."""

from __future__ import annotations

import os
import sys

# Vercel executes this file directly; make the sibling package importable without installation.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from teachme.app import create_app  # noqa: E402

app = create_app()
