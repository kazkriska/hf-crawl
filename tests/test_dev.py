from __future__ import annotations
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import Config, setup_logging
from orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_dev_500_list(dev_config):
    """Dev test: fetch 500 models from list phase."""
    config = Config.from_yaml(dev_config, max_items=500)
    setup_logging(config)
    
    orchestrator = Orchestrator(config)
    await orchestrator.run("list")
    
    import duckdb
    conn = duckdb.connect(config.storage.duckdb_path)
    count = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    conn.close()
    assert count == 500, f"Expected 500 models, got {count}"


@pytest.mark.asyncio
async def test_dev_500_all_phases(dev_config):
    """Dev test: run all 3 phases with 500 items."""
    config = Config.from_yaml(dev_config, max_items=500)
    setup_logging(config)
    
    orchestrator = Orchestrator(config)
    await orchestrator.run("all")
    
    import duckdb
    conn = duckdb.connect(config.storage.duckdb_path)
    list_count = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    info_count = conn.execute("SELECT COUNT(*) FROM model_info").fetchone()[0]
    card_count = conn.execute("SELECT COUNT(*) FROM model_card").fetchone()[0]
    conn.close()
    
    assert list_count == 500, f"Expected 500 list items, got {list_count}"
    assert info_count > 0, f"Expected some info items, got {info_count}"
    assert card_count > 0, f"Expected some card items, got {card_count}"
