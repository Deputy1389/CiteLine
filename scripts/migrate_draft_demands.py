"""
Pass 055: Create draft_demands table in production Supabase.

Run once against the production database:
    python scripts/migrate_draft_demands.py

Safe to run multiple times — uses CREATE TABLE IF NOT EXISTS.
"""
from __future__ import annotations

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from packages.db.database import get_engine
from sqlalchemy import text


DDL = """
CREATE TABLE IF NOT EXISTS draft_demands (
    id          VARCHAR(120) PRIMARY KEY,
    case_id     VARCHAR(120) NOT NULL,
    run_id      VARCHAR(120) NOT NULL REFERENCES runs(id),
    sections    JSONB NOT NULL DEFAULT '{}',
    tone        VARCHAR(20) NOT NULL DEFAULT 'moderate',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_draft_demands_case_id ON draft_demands(case_id);
CREATE INDEX IF NOT EXISTS idx_draft_demands_run_id ON draft_demands(run_id);
"""


def main() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(DDL))
    print("✓ draft_demands table created (or already exists)")


if __name__ == "__main__":
    main()
