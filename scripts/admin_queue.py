"""
scripts/admin_queue.py — Pass 043: Minimal admin CLI for the run queue.

Usage:
    python scripts/admin_queue.py enqueue --packet PATH --mode INTERNAL|MEDIATION [--firm-id ID]
    python scripts/admin_queue.py status  --run-id RUN_ID
    python scripts/admin_queue.py requeue --run-id RUN_ID
    python scripts/admin_queue.py cancel  --run-id RUN_ID
    python scripts/admin_queue.py list    [--status queued|running|failed|...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _get_db():
    from apps.api.database import SessionLocal  # type: ignore[import]
    return SessionLocal()


def cmd_enqueue(args: argparse.Namespace) -> int:
    from packages.db.models import Run, _uuid, utcnow
    from apps.worker.lib.queue import build_idempotency_key, enqueue_run, STATUS_QUEUED

    packet = Path(args.packet)
    if not packet.exists():
        print(f"ERROR: packet not found: {packet}", file=sys.stderr)
        return 1

    packet_sha = hashlib.sha256(packet.read_bytes()).hexdigest()
    firm_id = args.firm_id or "local"
    export_mode = args.mode.upper()

    # Use unknown versions if not determinable locally; proper values set by pipeline at claim time.
    policy_version = args.policy_version or "unknown"
    signal_layer_version = args.signal_layer_version or "unknown"

    ikey = build_idempotency_key(firm_id, packet_sha, export_mode, policy_version, signal_layer_version)

    db = _get_db()
    try:
        # Check if existing before creating a row
        from packages.db.models import Run
        existing = db.query(Run).filter(Run.idempotency_key == ikey).first()
        if existing is not None:
            print(json.dumps({"action": "existing", "run_id": existing.id, "status": existing.status}))
            return 0

        # Create matter-less run for local/admin use (matter_id required by FK — use a sentinel)
        run_id = _uuid()
        row = Run(
            id=run_id,
            matter_id=args.matter_id or "admin-local",
            status=STATUS_QUEUED,
            config_json={"export_mode": export_mode, "packet_path": str(packet)},
        )
        db.add(row)
        db.flush()

        final_run_id, created = enqueue_run(db, run_id, ikey)
        db.commit()
        print(json.dumps({"action": "enqueued" if created else "existing", "run_id": final_run_id}))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_status(args: argparse.Namespace) -> int:
    from packages.db.models import Run, Artifact
    db = _get_db()
    try:
        run = db.query(Run).filter(Run.id == args.run_id).first()
        if run is None:
            print(f"ERROR: run_id not found: {args.run_id}", file=sys.stderr)
            return 1
        artifacts = db.query(Artifact).filter(Artifact.run_id == run.id).all()
        print(json.dumps({
            "run_id": run.id,
            "status": run.status,
            "attempt": run.attempt,
            "worker_id": run.worker_id,
            "lock_expires_at": str(run.lock_expires_at) if run.lock_expires_at else None,
            "error_class": run.error_class,
            "error_message": run.error_message,
            "started_at": str(run.started_at) if run.started_at else None,
            "finished_at": str(run.finished_at) if run.finished_at else None,
            "artifacts": [
                {"type": a.artifact_type, "write_state": a.write_state, "uri": a.storage_uri}
                for a in artifacts
            ],
        }, indent=2))
        return 0
    finally:
        db.close()


def cmd_requeue(args: argparse.Namespace) -> int:
    from packages.db.models import Run
    from apps.worker.lib.queue import STATUS_FAILED, STATUS_QUEUED, MAX_ATTEMPTS
    db = _get_db()
    try:
        run = db.query(Run).filter(Run.id == args.run_id).first()
        if run is None:
            print(f"ERROR: run_id not found: {args.run_id}", file=sys.stderr)
            return 1
        if run.status != STATUS_FAILED:
            print(f"ERROR: can only requeue failed runs (current status={run.status})", file=sys.stderr)
            return 1
        run.status = STATUS_QUEUED
        run.attempt += 1
        run.lock_expires_at = None
        run.worker_id = None
        run.error_message = None
        db.commit()
        print(json.dumps({"action": "requeued", "run_id": run.id, "attempt": run.attempt}))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_cancel(args: argparse.Namespace) -> int:
    from apps.worker.lib.queue import mark_canceled
    db = _get_db()
    try:
        mark_canceled(db, args.run_id)
        db.commit()
        print(json.dumps({"action": "canceled", "run_id": args.run_id}))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_list(args: argparse.Namespace) -> int:
    from packages.db.models import Run
    db = _get_db()
    try:
        q = db.query(Run)
        if args.status:
            q = q.filter(Run.status == args.status)
        runs = q.order_by(Run.created_at.desc()).limit(50).all()
        rows = [
            {"run_id": r.id, "status": r.status, "attempt": r.attempt,
             "created_at": str(r.created_at), "error_class": r.error_class}
            for r in runs
        ]
        print(json.dumps(rows, indent=2))
        return 0
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="CiteLine queue admin CLI (Pass 043)")
    sub = parser.add_subparsers(dest="command")

    p_enqueue = sub.add_parser("enqueue", help="Enqueue a new run")
    p_enqueue.add_argument("--packet", required=True)
    p_enqueue.add_argument("--mode", required=True, choices=["INTERNAL", "MEDIATION"])
    p_enqueue.add_argument("--firm-id", dest="firm_id", default=None)
    p_enqueue.add_argument("--matter-id", dest="matter_id", default=None)
    p_enqueue.add_argument("--policy-version", dest="policy_version", default=None)
    p_enqueue.add_argument("--signal-layer-version", dest="signal_layer_version", default=None)

    p_status = sub.add_parser("status", help="Show run status")
    p_status.add_argument("--run-id", dest="run_id", required=True)

    p_requeue = sub.add_parser("requeue", help="Re-queue a failed run")
    p_requeue.add_argument("--run-id", dest="run_id", required=True)

    p_cancel = sub.add_parser("cancel", help="Cancel a run (best-effort)")
    p_cancel.add_argument("--run-id", dest="run_id", required=True)

    p_list = sub.add_parser("list", help="List runs")
    p_list.add_argument("--status", default=None)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    dispatch = {
        "enqueue": cmd_enqueue,
        "status": cmd_status,
        "requeue": cmd_requeue,
        "cancel": cmd_cancel,
        "list": cmd_list,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
