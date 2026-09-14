from __future__ import annotations
import hashlib
import time
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def extract_yaml_frontmatter(text: str) -> dict:
    """Extract YAML metadata from markdown frontmatter."""
    import yaml
    if not text:
        return {}
    text = text.strip()
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                return {}
    return {}
