"""
Worker runner script.
Polls the database for pending runs and executes the pipeline.
"""
import logging
import time
import sys
import os
import uuid
import threading
import platform
from datetime import datetime, timezone, timedelta

# Add project root to path if needed (though usually handled by python -m)
sys.path.append(os.getcwd())

from packages.db.database import get_session
from packages.db.models import Run
from apps.worker.pipeline import run_pipeline

logger = logging.getLogger(__name__)

# Config
HEARTBEAT_INTERVAL = 10  # Seconds
STALE_THRESHOLD_MINUTES = 10
WORKER_ID = f"{platform.node()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"

def get_utc_now():
    return datetime.now(timezone.utc)

def claim_run() -> str | None:
    """Find and atomically claim a pending run."""
    with get_session() as session:
        # 1. Find a pending run (FIFO)
        # We look for pending runs OR stale runs
        stale_cutoff = get_utc_now() - timedelta(minutes=STALE_THRESHOLD_MINUTES)
        
        # Check for stale runs first (recovery)
        stale_run = (
            session.query(Run)
            .filter(Run.status == "running")
            .filter(Run.heartbeat_at < stale_cutoff)
            .first()
        )
        
        target_run = None
        if stale_run:
            logger.warning(f"Found stale run {stale_run.id} (last heartbeat {stale_run.heartbeat_at}). Reclaiming.")
            target_run = stale_run
        else:
            # Normal pending run
            target_run = session.query(Run).filter_by(status="pending").order_by(Run.created_at).first()

        if not target_run:
            return None
            
        run_id = target_run.id
        
        # 2. Atomic Update
        # We ensure we only claim if status is still what we expect
        # For stale runs, we reset them to running
        
        # Note: SQLAlchemy update() with synchronization_session=False is efficient
        # but returning row count is DB-specific. 
        # Here we do a targeted update with filter.
        
        expected_status = "running" if stale_run else "pending"
        
        rows_updated = (
            session.query(Run)
            .filter(Run.id == run_id)
            .filter(Run.status == expected_status)
            .update({
                "status": "running",
                "worker_id": WORKER_ID,
                "claimed_at": get_utc_now(),
                "heartbeat_at": get_utc_now(),
            })
        )
        
        session.commit()
        
        if rows_updated == 1:
            return run_id
        else:
            # Race condition: someone else claimed it
            logger.info(f"Race condition claiming run {run_id}. Retrying...")
            return None

class HeartbeatThread(threading.Thread):
    def __init__(self, run_id: str):
        super().__init__(daemon=True)
        self.run_id = run_id
        self.stop_event = threading.Event()

    def run(self):
        logger.debug(f"Heartbeat started for {self.run_id}")
        while not self.stop_event.is_set():
            try:
                with get_session() as session:
                    session.query(Run).filter_by(id=self.run_id).update({
                        "heartbeat_at": get_utc_now()
                    })
                    session.commit()
            except Exception as e:
                logger.error(f"Heartbeat failed for {self.run_id}: {e}")
            
            self.stop_event.wait(HEARTBEAT_INTERVAL)
        logger.debug(f"Heartbeat stopped for {self.run_id}")

    def stop(self):
        self.stop_event.set()

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logger.info(f"Worker runner started. ID: {WORKER_ID}")
    
    while True:
        try:
            run_id = claim_run()
            if run_id:
                logger.info(f"Claimed run {run_id}. Starting pipeline...")
                
                # Start heartbeat
                beater = HeartbeatThread(run_id)
                beater.start()
                
                try:
                    run_pipeline(run_id)
                finally:
                    beater.stop()
                    beater.join()
                    
                logger.info(f"Run {run_id} processing complete.")
            else:
                time.sleep(2)
        
        except KeyboardInterrupt:
            logger.info("Worker stopping by user request.")
            break
        except Exception as exc:
            logger.exception(f"Unexpected error in worker loop: {exc}")
            time.sleep(5)

if __name__ == "__main__":
    main()
