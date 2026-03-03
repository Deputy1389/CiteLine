"""
scripts/sweep_stuck_runs.py — Pass 043: Sweeper for expired run leases.

Finds runs where status=running and lock_expires_at < now(), then:
  - Re-queues them (incrementing attempt) if attempt < MAX_ATTEMPTS
  - Dead-letters them (status=failed) if attempt >= MAX_ATTEMPTS

Run this on a cron / systemd timer every 2 minutes on the worker host:
    python scripts/sweep_stuck_runs.py
    python scripts/sweep_stuck_runs.py --dry-run

Exit codes:
    0 — sweep completed (even if nothing was requeued)
    1 — error connecting to DB or running sweep
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.worker.lib.queue import MAX_ATTEMPTS, STATUS_FAILED, STATUS_RUNNING, requeue_expired_leases
from packages.db.models import Run


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep expired run leases and requeue or dead-letter.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without committing.")
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS, help=f"Max attempts before dead-lettering (default: {MAX_ATTEMPTS}).")
    args = parser.parse_args()

    try:
        from apps.api.database import SessionLocal  # type: ignore[import]
    except ImportError:
        print("ERROR: Could not import SessionLocal from apps.api.database", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Count what we'd touch before doing anything
        expired = (
            db.query(Run)
            .filter(Run.status == STATUS_RUNNING, Run.lock_expires_at < now)
            .all()
        )

        if not expired:
            print("sweep: no expired leases found")
            return 0

        print(f"sweep: found {len(expired)} expired lease(s)")
        for run in expired:
            tag = "dead-letter" if run.attempt >= args.max_attempts else "requeue"
            print(f"  [{tag}] run_id={run.id} attempt={run.attempt} lock_expired={run.lock_expires_at}")

        if args.dry_run:
            print("sweep: --dry-run mode, no changes committed")
            return 0

        requeued = requeue_expired_leases(db, max_attempts=args.max_attempts)
        db.commit()

        dead = sum(1 for r in expired if r.attempt >= args.max_attempts)
        print(json.dumps({
            "sweep_at": now.isoformat(),
            "expired_found": len(expired),
            "requeued": requeued,
            "dead_lettered": dead,
        }))
        return 0

    except Exception as exc:
        db.rollback()
        print(f"ERROR: sweep failed: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
