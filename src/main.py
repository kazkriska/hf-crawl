from __future__ import annotations
import asyncio
import sys
from pathlib import Path

import click
import structlog

from src.config import Config, setup_logging
from src.orchestrator import Orchestrator


@click.command()
@click.option(
    "--phase",
    type=click.Choice(["all", "list", "info", "card"]),
    default="all",
    help="Which phase to run",
)
@click.option(
    "--max-items",
    type=int,
    default=None,
    help="Maximum number of items to fetch (for testing)",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True),
    default="config/config.dev.yaml",
    help="Path to config file",
)
def main(phase: str, max_items: int | None, config_path: str) -> None:
    """HF Crawl — Fetch model cards from Hugging Face Hub."""
    config = Config.from_yaml(config_path, max_items=max_items)
    setup_logging(config)

    logger = structlog.get_logger(__name__)
    logger.info(
        "hf_crawl_starting",
        phase=phase,
        environment=config.environment,
        max_items=max_items,
    )

    orchestrator = Orchestrator(config)

    try:
        asyncio.run(orchestrator.run(phase))
        logger.info("hf_crawl_completed")
    except KeyboardInterrupt:
        logger.info("hf_crawl_interrupted")
        sys.exit(1)
    except Exception as e:
        logger.error("hf_crawl_failed", error=str(e), exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
