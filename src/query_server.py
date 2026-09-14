from __future__ import annotations
import asyncio
import json
import os
import time
from collections import deque
from threading import Lock, Thread
from typing import Any

import structlog

from src.config import Config
from src.components.storage import Storage
from src.components.checkpoint import CheckpointManager

logger = structlog.get_logger(__name__)


class QueryServer:
    """HTTP API for querying crawl data while crawler is running.
    
    Uses a single-threaded query queue to serialize all database access,
    preventing DuckDB lock conflicts with the writer.
    """

    def __init__(self, config: Config, storage: Storage):
        self._config = config
        self._storage = storage
        self._lock = Lock()
        self._query_queue = deque()
        self._result_cache = {}
        self._query_thread = None
        self._running = False
        self._app = None

    def _query_worker(self):
        """Worker thread that processes queries one at a time."""
        while self._running:
            if self._query_queue:
                query_id, query_func = self._query_queue.popleft()
                try:
                    result = query_func()
                    with self._lock:
                        self._result_cache[query_id] = {"status": "ok", "data": result}
                except Exception as e:
                    with self._lock:
                        self._result_cache[query_id] = {"status": "error", "error": str(e)}
            else:
                time.sleep(0.1)

    async def start(self, port: int = 8001) -> None:
        """Start the query server."""
        from aiohttp import web
        
        self._running = True
        self._query_thread = Thread(target=self._query_worker, daemon=True)
        self._query_thread.start()
        
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

    def _execute_query(self, query_func, timeout: float = 30.0):
        """Submit a query to the queue and wait for result."""
        import uuid
        query_id = str(uuid.uuid4())
        
        with self._lock:
            self._result_cache.pop(query_id, None)
        
        self._query_queue.append((query_id, query_func))
        
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                if query_id in self._result_cache:
                    result = self._result_cache.pop(query_id)
                    if result["status"] == "ok":
                        return result["data"]
                    else:
                        raise Exception(result["error"])
            time.sleep(0.05)
        
        raise TimeoutError(f"Query timed out after {timeout}s")

    async def health(self, request) -> Any:
        from aiohttp import web
        return web.json_response({"status": "ok"})

    async def stats(self, request) -> Any:
        from aiohttp import web
        try:
            result = self._execute_query(lambda: {
                "models_list": self._storage.get_list_count(),
                "model_info": self._storage.get_info_count(),
                "model_card": self._storage.get_card_count(),
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
            
            def query():
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
                
                result = self._storage.db.execute(sql, params).fetchall()
                return [{"model_id": r[0], "author": r[1], "downloads": r[2], "likes": r[3], "pipeline_tag": r[4], "created_at": r[5]} for r in result]
            
            result = self._execute_query(query)
            return web.json_response({"models": result, "count": len(result)})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)

    async def model_info(self, request) -> Any:
        from aiohttp import web
        try:
            model_id = request.match_info['id']
            
            def query():
                result = self._storage.db.execute("SELECT * FROM model_info WHERE model_id = ?", [model_id]).fetchone()
                if not result:
                    return None
                columns = [desc[0] for desc in self._storage.db.description]
                return dict(zip(columns, result))
            
            result = self._execute_query(query)
            if result is None:
                return web.json_response({"error": "not found"}, status=404)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)

    async def model_card(self, request) -> Any:
        from aiohttp import web
        try:
            model_id = request.match_info['id']
            
            def query():
                result = self._storage.db.execute("SELECT * FROM model_card WHERE model_id = ?", [model_id]).fetchone()
                if not result:
                    return None
                columns = [desc[0] for desc in self._storage.db.description]
                return dict(zip(columns, result))
            
            result = self._execute_query(query)
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
            
            def query():
                result = self._storage.db.execute(sql).fetchall()
                columns = [desc[0] for desc in self._storage.db.description] if self._storage.db.description else []
                rows = [dict(zip(columns, row)) for row in result]
                return {"columns": columns, "rows": rows}
            
            result = self._execute_query(query)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=503)
