"""
One-shot worker runner for Cron jobs.
Claims one pending run, processes it, and exits.
"""
import logging
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from packages.db.database import init_db
from apps.worker.runner import claim_run
from apps.worker.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("linecite.worker.once")

def main():
    logger.info("One-shot worker starting...")
    init_db()
    
    run_id = claim_run()
    if run_id:
        logger.info(f"Processing claimed run: {run_id}")
        try:
            run_pipeline(run_id)
            logger.info(f"Successfully finished run {run_id}")
        except Exception:
            logger.exception(f"Failed to process run {run_id}")
            sys.exit(1)
    else:
        logger.info("No pending runs found.")

if __name__ == "__main__":
    main()
