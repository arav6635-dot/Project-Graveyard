from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import psycopg

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE = BASE_DIR / "graveyard.db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Project Graveyard data from SQLite to Neon Postgres."
    )
    parser.add_argument(
        "--sqlite-path",
        default=str(DEFAULT_SQLITE),
        help="Path to sqlite db file (default: ./graveyard.db)",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "").strip(),
        help="Postgres/Neon connection URL. Falls back to DATABASE_URL env var.",
    )
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="Truncate target tables before insert.",
    )
    return parser.parse_args()


def ensure_schema(pg: psycopg.Connection) -> None:
    pg.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id BIGINT PRIMARY KEY,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            category TEXT NOT NULL,
            status TEXT NOT NULL,
            idea_origin TEXT,
            problem_target TEXT,
            target_audience TEXT,
            stack TEXT,
            team_size INTEGER,
            duration_months INTEGER,
            budget_range TEXT,
            timeline TEXT,
            what_happened TEXT,
            why_failed TEXT,
            lessons_learned TEXT,
            burnout_level INTEGER DEFAULT 0,
            market_signal INTEGER DEFAULT 0,
            tech_debt_level INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS failure_causes (
            id BIGINT PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_cause_votes (
            id BIGINT PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            cause_id BIGINT NOT NULL REFERENCES failure_causes(id) ON DELETE CASCADE,
            votes INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'crowd',
            UNIQUE(project_id, cause_id)
        );

        CREATE TABLE IF NOT EXISTS project_tags (
            id BIGINT PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, tag)
        );

        CREATE TABLE IF NOT EXISTS analysis_reports (
            id BIGINT PRIMARY KEY,
            project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ai_analytics_cache (
            id BIGINT PRIMARY KEY,
            fingerprint TEXT UNIQUE NOT NULL,
            model TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )


def truncate_tables(pg: psycopg.Connection) -> None:
    pg.execute(
        """
        TRUNCATE TABLE
            ai_analytics_cache,
            analysis_reports,
            project_tags,
            project_cause_votes,
            failure_causes,
            projects
        CASCADE;
        """
    )


def fetch_rows(sqlite_conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return sqlite_conn.execute(f"SELECT * FROM {table} ORDER BY id ASC").fetchall()


def insert_rows(pg: psycopg.Connection, table: str, rows: list[sqlite3.Row]) -> None:
    if not rows:
        return

    cols = rows[0].keys()
    col_list = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    update_cols = ", ".join([f"{c}=EXCLUDED.{c}" for c in cols if c != "id"])
    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {update_cols};"
    )

    values = [tuple(row[c] for c in cols) for row in rows]
    with pg.cursor() as cur:
        cur.executemany(sql, values)


def fix_sequences(pg: psycopg.Connection) -> None:
    sequence_tables = [
        "projects",
        "failure_causes",
        "project_cause_votes",
        "project_tags",
        "analysis_reports",
        "ai_analytics_cache",
    ]
    for table in sequence_tables:
        pg.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1), true) FROM {table};"
        )


def main() -> None:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("Missing --database-url (or set DATABASE_URL env var).")

    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    with psycopg.connect(args.database_url) as pg:
        pg.autocommit = False
        ensure_schema(pg)
        if args.truncate_first:
            truncate_tables(pg)

        for table in [
            "projects",
            "failure_causes",
            "project_cause_votes",
            "project_tags",
            "analysis_reports",
            "ai_analytics_cache",
        ]:
            rows = fetch_rows(sqlite_conn, table)
            insert_rows(pg, table, rows)
            print(f"migrated {table}: {len(rows)} rows")

        fix_sequences(pg)
        pg.commit()

    sqlite_conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
