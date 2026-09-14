from __future__ import annotations
import asyncio
import json
import os
import time
from aiohttp import web
from typing import Any

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
        self._setup_routes()

    def _setup_routes(self) -> None:
        self._app.router.add_get('/health', self.health)
        self._app.router.add_get('/stats', self.stats)
        self._app.router.add_get('/models', self.models)
        self._app.router.add_get('/model/{id}', self.model_info)
        self._app.router.add_get('/cards/{id}', self.model_card)
        self._app.router.add_post('/sql', self.raw_sql)

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def stats(self, request: web.Request) -> web.Response:
        try:
            list_count = self._storage.get_list_count()
            info_count = self._storage.get_info_count()
            card_count = self._storage.get_card_count()
            return web.json_response({
                "models_list": list_count,
                "model_info": info_count,
                "model_card": card_count,
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def models(self, request: web.Request) -> web.Response:
        try:
            limit = int(request.query.get('limit', 100))
            offset = int(request.query.get('offset', 0))
            search = request.query.get('search', '')
            tag = request.query.get('tag', '')

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

            result = self._storage.db.execute(query, params).fetchall()
            models = [
                {
                    "model_id": r[0],
                    "author": r[1],
                    "downloads": r[2],
                    "likes": r[3],
                    "pipeline_tag": r[4],
                    "created_at": r[5],
                }
                for r in result
            ]
            return web.json_response({"models": models, "count": len(models)})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def model_info(self, request: web.Request) -> web.Response:
        try:
            model_id = request.match_info['id']
            result = self._storage.db.execute(
                "SELECT * FROM model_info WHERE model_id = ?", [model_id]
            ).fetchone()
            if not result:
                return web.json_response({"error": "not found"}, status=404)
            columns = [desc[0] for desc in self._storage.db.description]
            return web.json_response(dict(zip(columns, result)))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def model_card(self, request: web.Request) -> web.Response:
        try:
            model_id = request.match_info['id']
            result = self._storage.db.execute(
                "SELECT * FROM model_card WHERE model_id = ?", [model_id]
            ).fetchone()
            if not result:
                return web.json_response({"error": "not found"}, status=404)
            columns = [desc[0] for desc in self._storage.db.description]
            return web.json_response(dict(zip(columns, result)))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def raw_sql(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            query = body.get('query', '')
            if not query:
                return web.json_response({"error": "no query"}, status=400)
            result = self._storage.db.execute(query).fetchall()
            columns = [desc[0] for desc in self._storage.db.description] if self._storage.db.description else []
            rows = [dict(zip(columns, row)) for row in result]
            return web.json_response({"columns": columns, "rows": rows})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def start(self, port: int = 8001) -> None:
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info("query_server_started", port=port)
