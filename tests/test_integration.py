from __future__ import annotations
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import Config, setup_logging
from orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_integration_full_pipeline(dev_config):
    """Integration test: full pipeline with 50 items."""
    config = Config.from_yaml(dev_config, max_items=50)
    setup_logging(config)
    
    orchestrator = Orchestrator(config)
    await orchestrator.run("all")
    
    import duckdb
    conn = duckdb.connect(config.storage.duckdb_path)
    list_count = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    info_count = conn.execute("SELECT COUNT(*) FROM model_info").fetchone()[0]
    card_count = conn.execute("SELECT COUNT(*) FROM model_card").fetchone()[0]
    
    assert list_count == 50
    assert info_count > 0
    assert card_count > 0
    
    # Verify FK integrity
    all_ids = {r[0] for r in conn.execute("SELECT model_id FROM models_list").fetchall()}
    info_ids = {r[0] for r in conn.execute("SELECT model_id FROM model_info").fetchall()}
    card_ids = {r[0] for r in conn.execute("SELECT model_id FROM model_card").fetchall()}
    conn.close()
    
    assert info_ids.issubset(all_ids), f"Info IDs not subset of list IDs"
    assert card_ids.issubset(all_ids), f"Card IDs not subset of list IDs"


@pytest.mark.asyncio
async def test_integration_resume_across_phases(dev_config):
    """Integration test: resume from checkpoint across phases."""
    import duckdb
    
    # Run list phase first
    config1 = Config.from_yaml(dev_config, max_items=30)
    setup_logging(config1)
    orchestrator1 = Orchestrator(config1)
    await orchestrator1.run("list")
    
    conn = duckdb.connect(config1.storage.duckdb_path)
    count1 = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    conn.close()
    assert count1 == 30
    
    # Now run all phases (should resume list from 30, then continue to info/card)
    config2 = Config.from_yaml(dev_config, max_items=50)
    setup_logging(config2)
    orchestrator2 = Orchestrator(config2)
    await orchestrator2.run("all")
    
    conn = duckdb.connect(config2.storage.duckdb_path)
    list_count = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
    assert list_count == 50, f"Expected 50 list items after resume, got {list_count}"
    
    info_count = conn.execute("SELECT COUNT(*) FROM model_info").fetchone()[0]
    conn.close()
    assert info_count > 0
