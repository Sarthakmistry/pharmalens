"""
DataPipelines/compiler-job/entrypoint.py
Cloud Run entry point for the PharmaLens compiler pipeline.

Triggered daily by Cloud Scheduler. Reads raw data from GCS,
writes compiled wiki pages and state back to GCS, then exits.

Required env vars (set in Cloud Run job config):
  GCS_MODE              = true
  GCS_BUCKET            = pharmalens-raw
  GOOGLE_CLOUD_PROJECT  = <project-id>
  GOOGLE_CLOUD_LOCATION = us-central1
  GOOGLE_GENAI_USE_VERTEXAI = True
"""

import os
import sys

# Ensure repo root is on the path so agents.* imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../..")

from dotenv import load_dotenv
load_dotenv()

from agents.orchestrator import run_daily_pipeline
from agents.logger import get_logger

logger = get_logger("pharmalens.compiler-job")


def main():
    logger.info("COMPILER-JOB | starting pipeline run")
    try:
        run_daily_pipeline()
        logger.info("COMPILER-JOB | pipeline completed successfully")
    except Exception as e:
        logger.error(f"COMPILER-JOB | pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
