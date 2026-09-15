from __future__ import annotations
import asyncio
import json
import os
import time
import uuid
from collections import deque
from typing import Any

import structlog

from src.config import Config
from src.components.storage import Storage
from src.components.checkpoint import CheckpointManager

logger = structlog.get_logger(__name__)


class QueryServer:
    """HTTP API for querying crawl data while crawler is running.
    
    Runs queries on the main asyncio event loop to share the DuckDB
    connection with the crawler without lock conflicts.
    """

    def __init__(self, config: Config, storage: Storage):
        self._config = config
        self._storage = storage
        self._app = None
        self._query_queue: deque[tuple[str, Any, asyncio.Future]] = deque()
        self._running = False

    async def _process_queries(self):
        """Process queries one at a time on the event loop."""
        while self._running:
            if self._query_queue:
                query_id, query_func, future = self._query_queue.popleft()
                try:
                    result = query_func(self._storage)
                    if not future.done():
                        future.set_result(result)
                except Exception as e:
                    if not future.done():
                        future.set_exception(e)
            await asyncio.sleep(0.05)

    async def _submit_query(self, query_func, timeout: float = 30.0):
        """Submit a query and wait for result."""
        query_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._query_queue.append((query_id, query_func, future))
        
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Query timed out after {timeout}s")

    async def start(self, port: int = 8001) -> None:
        """Start the query server."""
        from aiohttp import web
        
        self._running = True
        
        # Start query processor task
        asyncio.create_task(self._process_queries())
        
        self._app = web.Application()
        self._setup_routes()
        
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        logger.info("query_server_started", port=port)

    def _setup_routes(self) -> None:
        self._app.router.add_get('/health', self.health)
        self._app.router.add_get('/stats', self.stats)
        self._app.router.add_get('/models', self.models)
        self._app.router.add_get('/model/{id}', self.model_info)
        self._app.router.add_get('/cards/{id}', self.model_card)
        self._app.router.add_post('/sql', self.raw_sql)

    async def health(self, request) -> Any:
        from aiohttp import web
        return web.json_response({"status": "ok"})

    async def stats(self, request) -> Any:
        from aiohttp import web
        try:
            result = await self._submit_query(lambda storage: {
                "models_list": storage.get_list_count(),
                "model_info": storage.get_info_count(),
                "model_card": storage.get_card_count(),
            })
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)

    async def models(self, request) -> Any:
        from aiohttp import web
        try:
            limit = int(request.query.get('limit', 100))
            offset = int(request.query.get('offset', 0))
            search = request.query.get('search', '')
            tag = request.query.get('tag', '')
            
            def query(storage):
                sql = "SELECT model_id, author, downloads, likes, pipeline_tag, created_at FROM models_list WHERE 1=1"
                params = []
                if search:
                    sql += " AND model_id LIKE ?"
                    params.append(f"%{search}%")
                if tag:
                    sql += " AND pipeline_tag = ?"
                    params.append(tag)
                sql += " ORDER BY downloads DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                
                result = storage.db.execute(sql, params).fetchall()
                return [{"model_id": r[0], "author": r[1], "downloads": r[2], "likes": r[3], "pipeline_tag": r[4], "created_at": r[5]} for r in result]
            
            result = await self._submit_query(query)
            return web.json_response({"models": result, "count": len(result)})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)

    async def model_info(self, request) -> Any:
        from aiohttp import web
        try:
            model_id = request.match_info['id']
            
            def query(storage):
                result = storage.db.execute("SELECT * FROM model_info WHERE model_id = ?", [model_id]).fetchone()
                if not result:
                    return None
                columns = [desc[0] for desc in storage.db.description]
                return dict(zip(columns, result))
            
            result = await self._submit_query(query)
            if result is None:
                return web.json_response({"error": "not found"}, status=404)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)

    async def model_card(self, request) -> Any:
        from aiohttp import web
        try:
            model_id = request.match_info['id']
            
            def query(storage):
                result = storage.db.execute("SELECT * FROM model_card WHERE model_id = ?", [model_id]).fetchone()
                if not result:
                    return None
                columns = [desc[0] for desc in storage.db.description]
                return dict(zip(columns, result))
            
            result = await self._submit_query(query)
            if result is None:
                return web.json_response({"error": "not found"}, status=404)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)

    async def raw_sql(self, request) -> Any:
        from aiohttp import web
        try:
            body = await request.json()
            sql = body.get('query', '')
            if not sql:
                return web.json_response({"error": "no query"}, status=400)
            
            def query(storage):
                result = storage.db.execute(sql).fetchall()
                columns = [desc[0] for desc in storage.db.description] if storage.db.description else []
                rows = [dict(zip(columns, row)) for row in result]
                return {"columns": columns, "rows": rows}
            
            result = await self._submit_query(query)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)
