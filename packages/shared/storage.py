"""
Local disk and remote Supabase Storage helpers for uploads and artifacts.
"""
from __future__ import annotations

import hashlib
import os
import logging
from pathlib import Path
import requests
from dotenv import load_dotenv

# Load .env file BEFORE reading any environment variables
load_dotenv()

logger = logging.getLogger("linecite.storage")

DATA_DIR = Path(os.environ.get("DATA_DIR", "C:/CiteLine/data"))
UPLOADS_DIR = DATA_DIR / "uploads"
ARTIFACTS_DIR = DATA_DIR / "artifacts"

# Supabase configuration for shared storage between worker and API
SUPABASE_URL = os.environ.get("SUPABASE_URL")
if not SUPABASE_URL:
    url = os.environ.get("DATABASE_URL", "")
    if "supabase" in url:
        matches = [m for m in url.split("@") if "supabase" in m]
        if matches:
            domain = matches[0].split(":")[0].split(".")[1]
            if domain:
                # E.g. pooler.supabase.com or db.oqvemwshlhikhodlrjjk.supabase.co
                # We can't perfectly derive the REST URL from the pooler URL because
                # pooler URLs don't contain the project ref (like aws-0-us-west-2.pooler.supabase.com)
                pass

# Let's rely strictly on explicit environment variables for the REST API
SUPABASE_REST_URL = os.environ.get("SUPABASE_REST_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

# Feature flag: enable Supabase storage if we have the credentials
USE_SUPABASE_STORAGE = bool(SUPABASE_REST_URL and SUPABASE_SERVICE_KEY)

def ensure_dirs() -> None:
    """Create data directories if they don't exist."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

def sha256_bytes(data: bytes) -> str:
    """Compute sha256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()

def _supabase_upload(bucket: str, path: str, file_bytes: bytes, content_type: str = "application/pdf") -> None:
    """Upload a file to Supabase Object Storage."""
    if not USE_SUPABASE_STORAGE:
        return
    url = f"{SUPABASE_REST_URL}/storage/v1/object/{bucket}/{path}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type,
        "x-upsert": "true"
    }
    
    try:
        response = requests.post(url, headers=headers, data=file_bytes, timeout=30)
        if response.status_code not in (200, 201):
            logger.error(f"Failed to upload {path} to Supabase bucket {bucket}: {response.text}")
        else:
            logger.info(f"Successfully uploaded {path} to Supabase bucket {bucket}")
    except Exception as e:
        logger.error(f"Exception uploading to Supabase: {e}")

def _supabase_download(bucket: str, path: str, dest: Path) -> bool:
    """Download a file from Supabase Object Storage."""
    if not USE_SUPABASE_STORAGE:
        return False
    url = f"{SUPABASE_REST_URL}/storage/v1/object/{bucket}/{path}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"
    }
    
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        if response.status_code == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Successfully downloaded {path} from Supabase bucket {bucket}")
            return True
        else:
            logger.warning(f"Failed to download {path} from Supabase bucket {bucket}: {response.status_code} {response.text}")
    except Exception as e:
        logger.error(f"Exception downloading from Supabase: {e}")
    return False

def save_upload(source_document_id: str, file_bytes: bytes) -> Path:
    """Save uploaded PDF to local disk and Supabase. Returns the file path."""
    ensure_dirs()
    path = UPLOADS_DIR / f"{source_document_id}.pdf"
    path.write_bytes(file_bytes)
    
    if USE_SUPABASE_STORAGE:
        _supabase_upload("documents", f"{source_document_id}.pdf", file_bytes, "application/pdf")
        
    return path

def get_upload_path(source_document_id: str) -> Path:
    """Return the path to a previously-saved upload, attempting remote download if local fails."""
    path = UPLOADS_DIR / f"{source_document_id}.pdf"
    
    if not path.exists() and USE_SUPABASE_STORAGE:
        logger.info(f"Upload {source_document_id}.pdf not found locally. Fetching from Supabase...")
        _supabase_download("documents", f"{source_document_id}.pdf", path)
        
    return path

def save_artifact(run_id: str, filename: str, data: bytes) -> Path:
    """Save a generated artifact (PDF/CSV/JSON) to the run's artifact dir."""
    ensure_dirs()
    run_dir = ARTIFACTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    
    if USE_SUPABASE_STORAGE:
        content_type = "application/octet-stream"
        if filename.endswith(".pdf"):
            content_type = "application/pdf"
        elif filename.endswith(".csv"):
            content_type = "text/csv"
        elif filename.endswith(".json"):
            content_type = "application/json"
        elif filename.endswith(".md"):
            content_type = "text/markdown"
            
        _supabase_upload("artifacts", f"{run_id}/{filename}", data, content_type)
        
    return path

def get_artifact_dir(run_id: str) -> Path:
    """Return the artifact directory for a given run."""
    return ARTIFACTS_DIR / run_id

def get_artifact_path(run_id: str, filename: str) -> Path | None:
    """Return the full path to a specific artifact, fetching from remote if missing. Returns None if not found."""
    path = ARTIFACTS_DIR / run_id / filename

    if not path.exists() and USE_SUPABASE_STORAGE:
        logger.info(f"Artifact {run_id}/{filename} not found locally. Fetching from Supabase...")
        success = _supabase_download("artifacts", f"{run_id}/{filename}", path)
        if not success or not path.exists():
            return None
    elif not path.exists():
        return None

    return path
