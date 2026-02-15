"""
Worker runner script.
Polls the database for pending runs and executes the pipeline.
"""
import logging
import time
import sys
import os

# Add project root to path if needed (though usually handled by python -m)
sys.path.append(os.getcwd())

from packages.db.database import get_session
from packages.db.models import Run
from apps.worker.pipeline import run_pipeline

logger = logging.getLogger(__name__)

def claim_run() -> str | None:
    """Find and claim a pending run."""
    with get_session() as session:
        # Simple FIFO claim
        run = session.query(Run).filter_by(status="pending").first()
        if not run:
            return None
        
        run_id = run.id
        # We don't verify lock here because SQLite is single-file anyway, 
        # and we assume single worker for MVP or low conflicts.
        # Ideally we'd set status='claimed' or similar immediately.
        # But pipeline.py sets it to 'running' at start.
        # To avoid double claim, let's set it here?
        # pipeline.py line 71: run_row.status = "running"
        # If we optimize, we should set it here to prevent other workers from grabbing it.
        run.status = "running"
        session.commit()
        return run_id

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logger.info("Worker runner started. Polling for runs...")

    while True:
        try:
            run_id = claim_run()
            if run_id:
                logger.info(f"Claimed run {run_id}. Starting pipeline...")
                # Run the pipeline
                # note: run_pipeline also handles status updates, but we set it to 'running' to claim it.
                # run_pipeline will update it to 'running' again (redundant but safe) 
                # and then 'success'/'failed'.
                run_pipeline(run_id)
                logger.info(f"Run {run_id} processing complete.")
            else:
                # No work, sleep briefly
                time.sleep(2)
        
        except KeyboardInterrupt:
            logger.info("Worker stopping by user request.")
            break
        except Exception as exc:
            logger.exception(f"Unexpected error in worker loop: {exc}")
            time.sleep(5)

if __name__ == "__main__":
    main()
