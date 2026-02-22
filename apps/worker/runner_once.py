"""
Worker runner (one-shot mode for cron jobs).
Processes ONE pending run and exits.
For use with Render Cron Jobs (free tier).
"""
import logging
import sys
import os
import time

# Add project root to path
sys.path.append(os.getcwd())

from apps.worker.runner import claim_run, HeartbeatThread
from apps.worker.pipeline import run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Process one pending run and exit."""
    logger.info("Worker (one-shot) started. Looking for pending run...")

    run_id = claim_run()

    if not run_id:
        logger.info("No pending runs found. Exiting.")
        sys.exit(0)

    logger.info(f"Claimed run {run_id}. Starting pipeline...")

    # Start heartbeat thread
    beater = HeartbeatThread(run_id)
    beater.start()

    try:
        start = time.monotonic()
        run_pipeline(run_id)
        elapsed = time.monotonic() - start
        logger.info(f"Run {run_id} completed in {elapsed:.1f}s")
    finally:
        beater.stop()
        beater.join()

    logger.info(f"Run {run_id} processing complete. Exiting.")


if __name__ == "__main__":
    main()
