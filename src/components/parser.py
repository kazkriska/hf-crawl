from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from typing import Any

import yaml
import structlog

from ..utils import sha256hex

logger = structlog.get_logger(__name__)


def parse_model_list(raw: Any, page: int, cursor: str | None) -> list[dict[str, Any]]:
    """Parse a page of /api/models response into model_list records."""
    records = []
    if not isinstance(raw, list):
        if isinstance(raw, dict):
            raw = raw.get("models", [])
        else:
            return records
    for item in raw:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id") or item.get("modelId")
        if not model_id:
            continue
        records.append({
            "model_id": model_id,
            "author": item.get("author"),
            "created_at": _parse_timestamp(item.get("createdAt")),
            "last_modified": _parse_timestamp(item.get("lastModified")),
            "downloads": item.get("downloads", 0),
            "downloads_all_time": item.get("downloadsAllTime", 0),
            "likes": item.get("likes", 0),
            "trending_score": item.get("trendingScore"),
            "pipeline_tag": item.get("pipeline_tag") or item.get("pipelineTag"),
            "library_name": item.get("library_name") or item.get("libraryName"),
            "tags": _parse_tags(item.get("tags", [])),
            "etag": item.get("etag", ""),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "list_page": page,
            "list_cursor": cursor,
            "fetch_status": "success",
        })
    return records


def parse_model_info(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Parse /api/models/{id} response into model_info record."""
    if not isinstance(raw, dict):
        return None
    model_id = raw.get("id") or raw.get("modelId")
    if not model_id:
        return None
    return {
        "model_id": model_id,
        "sha": raw.get("sha"),
        "card_data": raw.get("cardData") or {},
        "base_models": _extract_base_models(raw),
        "datasets": raw.get("datasets") or [],
        "config": raw.get("config") or {},
        "eval_results": _extract_eval_results(raw),
        "gguf": raw.get("gguf") or {},
        "safetensors": _extract_safetensors(raw),
        "transformers_info": raw.get("transformersInfo") or {},
        "siblings": _extract_siblings(raw),
        "used_storage": raw.get("usedStorage"),
        "gated": raw.get("gated"),
        "disabled": raw.get("disabled", False),
        "etag": raw.get("etag", ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "success",
        "fetch_error": None,
    }


def parse_model_card(model_id: str, readme_text: str | None, etag: str) -> dict[str, Any] | None:
    """Parse README.md text into model_card record."""
    if not readme_text:
        return {
            "model_id": model_id,
            "readme_raw": "",
            "readme_size": 0,
            "yaml_metadata": {},
            "content_hash": sha256hex(""),
            "etag": etag,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fetch_status": "success",
            "fetch_error": None,
        }
    readme_size = len(readme_text.encode("utf-8"))
    yaml_meta = _extract_yaml_frontmatter(readme_text)
    return {
        "model_id": model_id,
        "readme_raw": readme_text,
        "readme_size": readme_size,
        "yaml_metadata": yaml_meta,
        "content_hash": sha256hex(readme_text),
        "etag": etag,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetch_status": "success",
        "fetch_error": None,
    }


def _parse_timestamp(ts: Any) -> str | None:
    """Parse various timestamp formats to ISO string."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, tz=timezone.utc).isoformat()
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(ts, str):
        if not ts.strip():
            return None
        return ts
    return None


def _parse_tags(tags: Any) -> list[str]:
    if isinstance(tags, list):
        return [str(t) for t in tags if t]
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    return []


def _extract_base_models(raw: dict) -> list[str]:
    """Extract base model IDs from model info."""
    bases = []
    card_data = raw.get("cardData", {}) or {}
    # Check various fields for base model info
    for field in ["base_model", "baseModel", "base_model_id"]:
        val = card_data.get(field) or raw.get(field)
        if val:
            if isinstance(val, str):
                bases.append(val)
            elif isinstance(val, list):
                bases.extend(str(v) for v in val)
    # Check config
    cfg = raw.get("config", {}) or {}
    for field in ["base_model", "base_model_name", "model_type"]:
        val = cfg.get(field)
        if val and isinstance(val, str):
            bases.append(val)
    return list(set(bases))


def _extract_eval_results(raw: dict) -> list[dict]:
    """Extract evaluation results from model info."""
    card_data = raw.get("cardData", {}) or {}
    metrics = card_data.get("metrics") or card_data.get("model-index") or []
    if isinstance(metrics, list):
        return metrics
    return []


def _extract_safetensors(raw: dict) -> dict:
    """Extract safetensors info."""
    tensors = raw.get("safetensors") or {}
    if isinstance(tensors, dict):
        return tensors
    return {}


def _extract_siblings(raw: dict) -> list[dict]:
    """Extract sibling files info."""
    siblings = raw.get("siblings") or []
    if isinstance(siblings, list):
        return [s for s in siblings if isinstance(s, dict)]
    return []


def _extract_yaml_frontmatter(text: str) -> dict:
    """Extract YAML from --- ... --- frontmatter."""
    if not text:
        return {}
    text = text.strip()
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        parsed = yaml.safe_load(parts[1])
        return parsed if isinstance(parsed, dict) else {}
    except yaml.YAMLError:
        return {}
