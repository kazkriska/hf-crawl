from __future__ import annotations
import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

# Ensure src is in path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def dev_config(tmp_dir):
    """Create a dev config for testing."""
    config_path = Path(tmp_dir) / "config.dev.yaml"
    data_dir = Path(tmp_dir) / "data" / "dev"
    checkpoint_dir = data_dir / "checkpoint"
    archive_dir = data_dir / "archive"
    logs_dir = Path(tmp_dir) / "logs"
    
    data_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    config = {
        "environment": "dev",
        "huggingface": {
            "token": "",
            "base_url": "https://huggingface.co",
            "sort_field": "createdAt",
            "sort_direction": 1,
            "page_size": 50,
        },
        "rate_limiting": {
            "max_requests_per_second": 3,
            "max_concurrent_requests": 3,
            "max_retries": 2,
            "backoff_base_seconds": 0.5,
            "backoff_max_seconds": 5.0,
        },
        "phase_gating": {
            "phase2_start_threshold_pct": 25,
            "phase3_start_threshold_pct": 100,
        },
        "storage": {
            "duckdb_path": str(data_dir / "model_cards.duckdb"),
            "jsonl_archive_dir": str(archive_dir),
        },
        "checkpoint": {
            "dir": str(checkpoint_dir),
            "save_every_n_pages": 1,
        },
        "logging": {
            "level": "DEBUG",
            "file": str(logs_dir / "dev.log"),
            "progress_every_n_models": 10,
        },
        "metrics": {
            "enabled": False,
            "port": 0,
        },
    }
    
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    
    return str(config_path)


@pytest.fixture
def dev_config_50(dev_config):
    """Dev config with max_items=50."""
    return dev_config, 50
