from __future__ import annotations
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import Config, setup_logging
from orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_smoke_list_only(dev_config):
    """Smoke test: fetch 50 models from list phase."""
    import os
    # Clear DB for clean test
    config_check = Config.from_yaml(dev_config)
    db_path = config_check.storage.duckdb_path
    if os.path.exists(db_path):
        os.remove(db_path)
    
    config = Config.from_yaml(dev_config, max_items=50)
    setup_logging(config)
    
    orchestrator = Orchestrator(config)
    await orchestrator.run("list")
    
    import duckdb
    conn = duckdb.connect(config.storage.duckdb_path)
    count = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    conn.close()
    assert count == 50, f"Expected 50 models, got {count}"


@pytest.mark.asyncio
async def test_smoke_all_phases(dev_config):
    """Smoke test: run all 3 phases with 50 items."""
    import os
    # Clear DB for clean test
    config_check = Config.from_yaml(dev_config)
    db_path = config_check.storage.duckdb_path
    if os.path.exists(db_path):
        os.remove(db_path)
    
    config = Config.from_yaml(dev_config, max_items=50)
    setup_logging(config)
    
    orchestrator = Orchestrator(config)
    await orchestrator.run("all")
    
    import duckdb
    conn = duckdb.connect(config.storage.duckdb_path)
    list_count = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    info_count = conn.execute("SELECT COUNT(*) FROM model_info").fetchone()[0]
    card_count = conn.execute("SELECT COUNT(*) FROM model_card").fetchone()[0]
    conn.close()
    
    assert list_count == 50, f"Expected 50 list items, got {list_count}"
    assert info_count > 0, f"Expected some info items, got {info_count}"
    assert card_count > 0, f"Expected some card items, got {card_count}"


@pytest.mark.asyncio
async def test_checkpoint_resume(dev_config):
    """Test that checkpoint resume works."""
    import duckdb
    import os
    
    # Clear DB for clean test
    config_check = Config.from_yaml(dev_config)
    db_path = config_check.storage.duckdb_path
    if os.path.exists(db_path):
        os.remove(db_path)
    
    # First run: fetch 25
    config1 = Config.from_yaml(dev_config, max_items=25)
    setup_logging(config1)
    orchestrator1 = Orchestrator(config1)
    await orchestrator1.run("list")
    
    conn = duckdb.connect(config1.storage.duckdb_path)
    count1 = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    conn.close()
    assert count1 == 25, f"Expected 25 after first run, got {count1}"
    
    # Second run: fetch 50 total (should resume from 25)
    config2 = Config.from_yaml(dev_config, max_items=50)
    setup_logging(config2)
    orchestrator2 = Orchestrator(config2)
    await orchestrator2.run("list")
    
    conn = duckdb.connect(config2.storage.duckdb_path)
    count2 = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    conn.close()
    assert count2 == 50, f"Expected 50 after resume, got {count2}"
