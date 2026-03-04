"""
Utilities for operational monitoring, incident normalization, and impact scoring.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

# Configuration for impact weighting
FIRM_STATUS_WEIGHTS = {
    "paid": 10.0,
    "trial": 5.0,
    "scraped": 1.0,
    "unknown": 1.0
}

REVENUE_EXPOSURE_BASE = 1.0

COMMON_ERROR_PATTERNS = [
    (r"connection error", "NET_CONN_ERROR"),
    (r"timeout", "TIMEOUT_ERROR"),
    (r"permission denied", "AUTH_PERM_ERROR"),
    (r"file not found", "IO_FILE_NOT_FOUND"),
    (r"no such file or directory", "IO_FILE_NOT_FOUND"),
    (r"database is locked", "DB_LOCK_ERROR"),
    (r"deadlock", "DB_DEADLOCK"),
    (r"out of memory", "SYS_OOM"),
    (r"disk full", "SYS_DISK_FULL"),
    (r"pdf artifact download invalid", "PDF_ARTIFACT_DOWNLOAD_INVALID"),
    (r"gate required bucket missing", "GATE_REQUIRED_BUCKET_MISSING"),
    (r"placeholder leak detected", "PLACEHOLDER_LEAK_DETECTED"),
    (r"extraction failed", "EXTRACTION_FAILED"),
    (r"demo generation failed", "DEMO_GENERATION_FAILED"),
]

def generate_fingerprint(message: str, stage: Optional[str] = None) -> str:
    """
    Generate a stable, canonical fingerprint from an error message.
    """
    if not message:
        return "UNKNOWN_ERROR"

    msg_lower = message.lower()
    
    # 1. Check for common patterns
    for pattern, key in COMMON_ERROR_PATTERNS:
        if re.search(pattern, msg_lower):
            if stage:
                return f"{stage.upper()}_{key}"
            return key

    # 2. Sanitize and hash if no pattern matches
    # Remove UUIDs, hex strings, and numbers to make the fingerprint stable
    sanitized = re.sub(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', '<uuid>', message)
    sanitized = re.sub(r'0x[0-9a-fA-F]+', '<hex>', sanitized)
    sanitized = re.sub(r'\d+', '<num>', sanitized)
    
    # Take a hash of the sanitized string to keep it a reasonable length
    h = hashlib.md5(sanitized.lower().encode()).hexdigest()[:12]
    
    prefix = stage.upper() if stage else "GENERIC"
    return f"{prefix}_ERR_{h}"

def calculate_impact_score(
    frequency: int, 
    firm_status: str = "trial", 
    revenue_exposure: float = 0.0
) -> float:
    """
    Calculate the impact score of an incident.
    Impact = (frequency_weight * firm_status_weight * (1 + revenue_exposure_weight))
    """
    status_weight = FIRM_STATUS_WEIGHTS.get(firm_status.lower(), 1.0)
    
    # We use log-ish scaling for frequency to avoid massive spikes from single firms 
    # but still reward higher frequency.
    freq_weight = frequency if frequency < 10 else (10 + (frequency ** 0.5))
    
    impact = freq_weight * status_weight * (1.0 + revenue_exposure)
    
    return round(impact, 2)
