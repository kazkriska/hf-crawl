from __future__ import annotations
import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from aiohttp import web
from typing import Any

import duckdb
import structlog

from src.config import Config
from src.components.storage import Storage
from src.components.checkpoint import CheckpointManager

logger = structlog.get_logger(__name__)


class QueryServer:
    """HTTP API for querying crawl data while crawler is running."""

    def __init__(self, config: Config, storage: Storage):
        self._config = config
        self._storage = storage
        self._app = web.Application()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._db_path = config.storage.duckdb_path
        self._setup_routes()

    def _setup_routes(self) -> None:
        self._app.router.add_get('/health', self.health)
        self._app.router.add_get('/stats', self.stats)
        self._app.router.add_get('/models', self.models)
        self._app.router.add_get('/model/{id}', self.model_info)
        self._app.router.add_get('/cards/{id}', self.model_card)
        self._app.router.add_post('/sql', self.raw_sql)

    def _get_readonly_conn(self):
        """Get a read-only connection to the database."""
        return duckdb.connect(self._db_path, read_only=True)

    async def _run_in_thread(self, func, *args):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    def _get_stats(self):
        conn = self._get_readonly_conn()
        try:
            list_count = conn.execute("SELECT COUNT(*) FROM models_list").fetchone()[0]
            info_count = conn.execute("SELECT COUNT(*) FROM model_info").fetchone()[0]
            card_count = conn.execute("SELECT COUNT(*) FROM model_card").fetchone()[0]
            return {"models_list": list_count, "model_info": info_count, "model_card": card_count}
        finally:
            conn.close()

    def _get_models(self, limit, offset, search, tag):
        conn = self._get_readonly_conn()
        try:
            query = "SELECT model_id, author, downloads, likes, pipeline_tag, created_at FROM models_list WHERE 1=1"
            params: list[Any] = []
            if search:
                query += " AND model_id LIKE ?"
                params.append(f"%{search}%")
            if tag:
                query += " AND pipeline_tag = ?"
                params.append(tag)
            query += " ORDER BY downloads DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            result = conn.execute(query, params).fetchall()
            return [{"model_id": r[0], "author": r[1], "downloads": r[2], "likes": r[3], "pipeline_tag": r[4], "created_at": r[5]} for r in result]
        finally:
            conn.close()

    def _get_model_info(self, model_id):
        conn = self._get_readonly_conn()
        try:
            result = conn.execute("SELECT * FROM model_info WHERE model_id = ?", [model_id]).fetchone()
            if not result:
                return None
            columns = [desc[0] for desc in conn.description]
            return dict(zip(columns, result))
        finally:
            conn.close()

    def _get_model_card(self, model_id):
        conn = self._get_readonly_conn()
        try:
            result = conn.execute("SELECT * FROM model_card WHERE model_id = ?", [model_id]).fetchone()
            if not result:
                return None
            columns = [desc[0] for desc in conn.description]
            return dict(zip(columns, result))
        finally:
            conn.close()

    def _run_sql(self, query):
        conn = self._get_readonly_conn()
        try:
            result = conn.execute(query).fetchall()
            columns = [desc[0] for desc in conn.description] if conn.description else []
            rows = [dict(zip(columns, row)) for row in result]
            return {"columns": columns, "rows": rows}
        finally:
            conn.close()

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def stats(self, request: web.Request) -> web.Response:
        try:
            result = await self._run_in_thread(self._get_stats)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def models(self, request: web.Request) -> web.Response:
        try:
            limit = int(request.query.get('limit', 100))
            offset = int(request.query.get('offset', 0))
            search = request.query.get('search', '')
            tag = request.query.get('tag', '')
            result = await self._run_in_thread(self._get_models, limit, offset, search, tag)
            return web.json_response({"models": result, "count": len(result)})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def model_info(self, request: web.Request) -> web.Response:
        try:
            model_id = request.match_info['id']
            result = await self._run_in_thread(self._get_model_info, model_id)
            if result is None:
                return web.json_response({"error": "not found"}, status=404)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def model_card(self, request: web.Request) -> web.Response:
        try:
            model_id = request.match_info['id']
            result = await self._run_in_thread(self._get_model_card, model_id)
            if result is None:
                return web.json_response({"error": "not found"}, status=404)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def raw_sql(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            query = body.get('query', '')
            if not query:
                return web.json_response({"error": "no query"}, status=400)
            result = await self._run_in_thread(self._run_sql, query)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def start(self, port: int = 8001) -> None:
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info("query_server_started", port=port)
