from __future__ import annotations
import gzip
import json
import os
import shutil
import time
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import structlog

from src.config import Config
from src.metrics import (
    DB_SIZE_BYTES,
    DISK_FREE_BYTES,
    BATCH_COMMIT_DURATION_SECONDS,
)
from src.components.checkpoint import CheckpointManager

logger = structlog.get_logger(__name__)


def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """DuckDB + JSONL archive storage for HF crawl data."""

    def __init__(self, config: Config, checkpoint: CheckpointManager):
        self._config = config
        self._checkpoint = checkpoint
        self._db: duckdb.DuckDBPyConnection | None = None
        self._archive_dir = Path(config.storage.jsonl_archive_dir)
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._batch: list[dict[str, Any]] = []
        self._batch_size = 1000

    @property
    def db(self) -> duckdb.DuckDBPyConnection:
        if self._db is None:
            raise RuntimeError("Storage not initialized — call .start() first")
        return self._db

    def start(self) -> None:
        os.makedirs(os.path.dirname(self._config.storage.duckdb_path), exist_ok=True)
        # Clean stale lock files (happens when container restarts without clean shutdown)
        lock_path = self._config.storage.duckdb_path + ".wal"
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass
        try:
            self._db = duckdb.connect(self._config.storage.duckdb_path)
        except Exception:
            # If still locked, try removing and retrying
            for suffix in [".wal", ".lock"]:
                f = self._config.storage.duckdb_path + suffix
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
            self._db = duckdb.connect(self._config.storage.duckdb_path)
        self._create_tables()
        self._update_disk_metrics()

    def close(self) -> None:
        if self._db:
            self._db.close()

    def _create_tables(self) -> None:
        """Create schema if not exists."""
        self._db.execute("""
            CREATE SEQUENCE IF NOT EXISTS models_list_id_seq START 1;
            CREATE TABLE IF NOT EXISTS models_list (
                model_id        VARCHAR PRIMARY KEY,
                author          VARCHAR,
                created_at      TIMESTAMP,
                last_modified   TIMESTAMP,
                downloads       BIGINT DEFAULT 0,
                downloads_all_time BIGINT DEFAULT 0,
                likes           INTEGER DEFAULT 0,
                trending_score  FLOAT,
                pipeline_tag    VARCHAR,
                library_name    VARCHAR,
                tags            JSON,
                etag            VARCHAR,
                fetched_at      TIMESTAMP,
                list_page       INTEGER,
                list_cursor     VARCHAR,
                fetch_status    VARCHAR DEFAULT 'success'
            );
        """)

        self._db.execute("""
            CREATE SEQUENCE IF NOT EXISTS model_info_id_seq START 1;
            CREATE TABLE IF NOT EXISTS model_info (
                model_id        VARCHAR PRIMARY KEY,
                sha             VARCHAR,
                card_data       JSON,
                base_models     JSON,
                datasets        JSON,
                config          JSON,
                eval_results    JSON,
                gguf            JSON,
                safetensors     JSON,
                transformers_info JSON,
                siblings        JSON,
                used_storage    BIGINT,
                gated           VARCHAR,
                disabled        BOOLEAN DEFAULT FALSE,
                etag            VARCHAR,
                fetched_at      TIMESTAMP,
                fetch_status    VARCHAR DEFAULT 'success',
                fetch_error     TEXT,
                FOREIGN KEY (model_id) REFERENCES models_list(model_id)
            );
        """)

        self._db.execute("""
            CREATE SEQUENCE IF NOT EXISTS model_card_id_seq START 1;
            CREATE TABLE IF NOT EXISTS model_card (
                model_id        VARCHAR PRIMARY KEY,
                readme_raw      TEXT,
                readme_size     INTEGER,
                yaml_metadata   JSON,
                content_hash    VARCHAR,
                etag            VARCHAR,
                fetched_at      TIMESTAMP,
                fetch_status    VARCHAR DEFAULT 'success',
                fetch_error     TEXT,
                FOREIGN KEY (model_id) REFERENCES models_list(model_id)
            );
        """)

    def _update_disk_metrics(self) -> None:
        try:
            if os.path.exists(self._config.storage.duckdb_path):
                DB_SIZE_BYTES.set(os.path.getsize(self._config.storage.duckdb_path))
            stat = shutil.disk_usage(self._config.storage.duckdb_path)
            DISK_FREE_BYTES.set(stat.free)
        except OSError:
            pass

    def get_list_count(self) -> int:
        result = self._db.execute("SELECT COUNT(*) FROM models_list").fetchone()
        return result[0] if result else 0

    def get_info_count(self) -> int:
        result = self._db.execute("SELECT COUNT(*) FROM model_info").fetchone()
        return result[0] if result else 0

    def get_card_count(self) -> int:
        result = self._db.execute("SELECT COUNT(*) FROM model_card").fetchone()
        return result[0] if result else 0

    def get_all_model_ids(self) -> list[str]:
        """Get all model IDs from the list table, sorted by created_at."""
        result = self._db.execute(
            "SELECT model_id FROM models_list ORDER BY created_at ASC"
        ).fetchall()
        return [r[0] for r in result]

    def get_info_model_ids(self) -> set[str]:
        result = self._db.execute("SELECT model_id FROM model_info").fetchall()
        return {r[0] for r in result}

    def get_card_model_ids(self) -> set[str]:
        result = self._db.execute("SELECT model_id FROM model_card").fetchall()
        return {r[0] for r in result}

    def upsert_model_list(self, records: Sequence[dict[str, Any]]) -> int:
        """Upsert model list records. Returns count written."""
        if not records:
            return 0
        start = time.monotonic()
        written = 0
        for r in records:
            try:
                self._db.execute("""
                    INSERT INTO models_list (
                        model_id, author, created_at, last_modified, downloads,
                        downloads_all_time, likes, trending_score, pipeline_tag,
                        library_name, tags, etag, fetched_at, list_page, list_cursor, fetch_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::JSON, ?, ?, ?, ?, ?)
                    ON CONFLICT (model_id) DO UPDATE SET
                        last_modified = excluded.last_modified,
                        downloads = excluded.downloads,
                        downloads_all_time = excluded.downloads_all_time,
                        likes = excluded.likes,
                        trending_score = excluded.trending_score,
                        pipeline_tag = excluded.pipeline_tag,
                        tags = excluded.tags,
                        etag = excluded.etag,
                        fetched_at = excluded.fetched_at,
                        fetch_status = excluded.fetch_status;
                """, [
                    r.get("model_id"), r.get("author"), r.get("created_at"),
                    r.get("last_modified"), r.get("downloads", 0),
                    r.get("downloads_all_time", 0), r.get("likes", 0),
                    r.get("trending_score"), r.get("pipeline_tag"),
                    r.get("library_name"), json.dumps(r.get("tags", [])),
                    r.get("etag"), r.get("fetched_at", _now_str()),
                    r.get("list_page"), r.get("list_cursor"),
                    r.get("fetch_status", "success"),
                ])
                written += 1
            except Exception as e:
                logger.error("upsert_list_error", error=str(e), model_id=r.get("model_id"))

        BATCH_COMMIT_DURATION_SECONDS.labels(phase="list").observe(time.monotonic() - start)
        self._append_to_archive("models_list", records)
        self._update_disk_metrics()
        return written

    def upsert_model_info(self, records: Sequence[dict[str, Any]]) -> int:
        """Upsert model info records. Returns count written."""
        if not records:
            return 0
        start = time.monotonic()
        written = 0
        for r in records:
            try:
                self._db.execute("""
                    INSERT INTO model_info (
                        model_id, sha, card_data, base_models, datasets, config,
                        eval_results, gguf, safetensors, transformers_info, siblings,
                        used_storage, gated, disabled, etag, fetched_at, fetch_status, fetch_error
                    ) VALUES (?, ?, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?::JSON, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (model_id) DO UPDATE SET
                        sha = excluded.sha,
                        card_data = excluded.card_data,
                        base_models = excluded.base_models,
                        datasets = excluded.datasets,
                        config = excluded.config,
                        eval_results = excluded.eval_results,
                        gguf = excluded.gguf,
                        safetensors = excluded.safetensors,
                        transformers_info = excluded.transformers_info,
                        siblings = excluded.siblings,
                        used_storage = excluded.used_storage,
                        gated = excluded.gated,
                        disabled = excluded.disabled,
                        etag = excluded.etag,
                        fetched_at = excluded.fetched_at,
                        fetch_status = excluded.fetch_status,
                        fetch_error = excluded.fetch_error;
                """, [
                    r.get("model_id"), r.get("sha"),
                    json.dumps(r.get("card_data", {})),
                    json.dumps(r.get("base_models", [])),
                    json.dumps(r.get("datasets", [])),
                    json.dumps(r.get("config", {})),
                    json.dumps(r.get("eval_results", [])),
                    json.dumps(r.get("gguf", {})),
                    json.dumps(r.get("safetensors", {})),
                    json.dumps(r.get("transformers_info", {})),
                    json.dumps(r.get("siblings", [])),
                    r.get("used_storage"),
                    r.get("gated"), r.get("disabled", False),
                    r.get("etag"), r.get("fetched_at", _now_str()),
                    r.get("fetch_status", "success"),
                    r.get("fetch_error"),
                ])
                written += 1
            except Exception as e:
                logger.error("upsert_info_error", error=str(e), model_id=r.get("model_id"))

        BATCH_COMMIT_DURATION_SECONDS.labels(phase="info").observe(time.monotonic() - start)
        self._append_to_archive("model_info", records)
        self._update_disk_metrics()
        return written

    def upsert_model_card(self, records: Sequence[dict[str, Any]]) -> int:
        """Upsert model card records. Returns count written."""
        if not records:
            return 0
        start = time.monotonic()
        written = 0
        for r in records:
            try:
                self._db.execute("""
                    INSERT INTO model_card (
                        model_id, readme_raw, readme_size, yaml_metadata, content_hash,
                        etag, fetched_at, fetch_status, fetch_error
                    ) VALUES (?, ?, ?, ?::JSON, ?, ?, ?, ?, ?)
                    ON CONFLICT (model_id) DO UPDATE SET
                        readme_raw = excluded.readme_raw,
                        readme_size = excluded.readme_size,
                        yaml_metadata = excluded.yaml_metadata,
                        content_hash = excluded.content_hash,
                        etag = excluded.etag,
                        fetched_at = excluded.fetched_at,
                        fetch_status = excluded.fetch_status,
                        fetch_error = excluded.fetch_error;
                """, [
                    r.get("model_id"), r.get("readme_raw"),
                    r.get("readme_size"),
                    json.dumps(r.get("yaml_metadata", {})),
                    r.get("content_hash"), r.get("etag"),
                    r.get("fetched_at", _now_str()),
                    r.get("fetch_status", "success"),
                    r.get("fetch_error"),
                ])
                written += 1
            except Exception as e:
                logger.error("upsert_card_error", error=str(e), model_id=r.get("model_id"))

        BATCH_COMMIT_DURATION_SECONDS.labels(phase="card").observe(time.monotonic() - start)
        self._append_to_archive("model_card", records)
        self._update_disk_metrics()
        return written

    def _append_to_archive(self, table: str, records: Sequence[dict[str, Any]]) -> None:
        """Append records to compressed JSONL archive."""
        if not records:
            return
        archive_path = self._archive_dir / f"{table}.jsonl.gz"
        try:
            with gzip.open(archive_path, "at", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, default=str) + "\n")
        except OSError as e:
            logger.warning("archive_write_error", path=str(archive_path), error=str(e))
