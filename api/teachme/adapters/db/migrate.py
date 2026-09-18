from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class SchemaOutOfDate(Exception):
    def __init__(self, pending: list[str]) -> None:
        super().__init__(f"database schema is behind; run `teachme migrate` to apply: {pending}")
        self.pending = pending


def available_versions() -> list[str]:
    return sorted(path.stem for path in MIGRATIONS_DIR.glob("*.sql"))


def applied_versions(conn: psycopg.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    conn.commit()
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [row["version"] for row in rows]


def pending_versions(conn: psycopg.Connection) -> list[str]:
    applied = set(applied_versions(conn))
    return [version for version in available_versions() if version not in applied]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply every pending migration in filename order, one transaction each."""
    applied_now: list[str] = []
    for version in pending_versions(conn):
        sql = (MIGRATIONS_DIR / f"{version}.sql").read_text(encoding="utf-8")
        conn.execute(sql)
        conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        conn.commit()
        applied_now.append(version)
    return applied_now


def ensure_schema_current(conn: psycopg.Connection) -> None:
    pending = pending_versions(conn)
    if pending:
        raise SchemaOutOfDate(pending)
