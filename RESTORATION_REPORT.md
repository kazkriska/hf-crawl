# HF Crawl Project - Full Restoration Report

## Date: 2026-09-15
## State: Fully Operational

---

## 1. Git Repository State

**Branch:** `main`
**Status:** Working tree clean
**Latest commits:**
- `0acb491` improv(web-ui)
- `67c7e20` increased fetch rate to maximize usage of rate-limits
- `1b895c8` Merge branch 'final-changes-remote'
- `ccbe83b` Merge branch 'container-diff-branch'
- `44cb08a` fetched changes from remote repository which is in working state as of now

---

## 2. Docker Container State

**Container:** `hf-crawl` on `192.168.1.240`
**Status:** Running
**Ports:**
- `8001` - Query API (aiohttp)
- `8501` - Web UI (Streamlit)

**Current crawl progress:** 1,270,366 models fetched

**Services confirmed working:**
| Service | Endpoint | Status |
|---------|----------|--------|
| Query API | `http://192.168.1.240:8001/stats` | ✅ |
| Web UI | `http://192.168.1.240:8501` | ✅ HTTP 200 |
| Crawler | Active | ✅ 1.27M+ fetched |
| Pushgateway | `192.168.1.11:9091` | ✅ `instance="prod"` |
| Loki | `192.168.1.11:3100` | ✅ Logs shipping |

---

## 3. Files Restored/Changed on Remote Container (`/etc/arcane/projects/hf-crawl-new-dockerized/`)

All files were replaced with clean versions from git `main` branch:

### Modified Files
| File | Changes |
|------|---------|
| `src/query_server.py` | Uses shared Storage connection (no read-only conflicts) |
| `src/orchestrator.py` | QueryServer import + startup on port 8001 |
| `src/components/storage.py` | WAL cleanup on start/close, guard against double-start |
| `hf-crawl-web/app.py` | New dashboard with Pipeline Tags page, search, expandable model lists |
| `config/config.prod.yaml` | Rate limits: 8 req/s, 15 concurrent |
| `docker-compose.yml` | Added port 8001, mounted `./hf-crawl-web` as volume, added `API_URL` env var |
| `Dockerfile` | Added streamlit + pandas to requirements, EXPOSE 8001 |
| `requirements.txt` | Added aiohttp, requests, streamlit, pandas |

### New Files
| File | Purpose |
|------|---------|
| `src/query_server.py` | HTTP API for querying crawl data while crawler runs |
| `src/monitoring.py` | MetricsPusher + LogShipper for Prometheus/Loki |

---

## 4. Git Branches

- `main` - Primary working branch (clean)
- `remotes/origin/container-diff-branch` - Deprecated
- `remotes/origin/final-changes-remote` - Merged

---

## 5. Key Features Implemented

### Query Server (`src/query_server.py`)
- Shares Storage instance with crawler (no separate connections)
- Endpoints: `/health`, `/stats`, `/models`, `/model/{id}`, `/cards/{id}`, `/sql`
- Thread-safe async HTTP server on port 8001

### Web UI (`hf-crawl-web/app.py`)
- **Overview:** Stats cards + top 20 models table
- **Pipeline Tags:** Bar chart with expandable model lists per tag
- **Model Search:** Searchable table with pipeline tag filter
- **Model Info:** Detailed metadata display
- **Model Cards:** README markdown + YAML metadata
- **Raw SQL:** Custom query runner

### Monitoring
- Prometheus metrics pushed to `192.168.1.11:9091`
- Logs shipped to Loki at `192.168.1.11:3100`
- Grafana dashboard: `grafana/dashboard.json`

### Crawl Configuration
- Sort: `createdAt` ascending
- Page size: 1000
- Rate: 8 req/s, 15 concurrent
- Phase gating: 25% for info, 100% for cards

---

## 6. Architecture

```
HF Crawler Container (192.168.1.240)
┌─────────────────────────────────────────────────┐
│  Crawler (src/main.py)                           │
│  ├── Phase 1: List (cursor pagination)          │
│  ├── Phase 2: Info (per-model fetch)            │
│  └── Phase 3: Card (README + YAML)              │
│                                                   │
│  Storage (DuckDB) ←── Query Server ──→ :8001    │
│                                    ↳ Web UI :8501│
└─────────────────────────────────────────────────┘
         │                      │
         ▼                      ▼
    Pushgateway              Loki/Grafana
    :9091                    :3100/:3000
```

---

## 7. Known Issues / Notes

1. **DuckDB concurrency:** Only one writer allowed. Query server shares Storage instance to avoid conflicts.
2. **51% models have null pipeline_tag:** This is normal Hugging Face behavior - many models are unclassified.
3. **Web UI runs in background:** Use `docker compose exec -d hf-crawl /app/entrypoint.sh web` to start.

---

## 8. Quick Commands

```bash
# Start web UI
docker compose exec -d hf-crawl /app/entrypoint.sh web

# Check stats
curl -s http://192.168.1.240:8001/stats

# View logs
docker compose logs -f

# Restart after code changes
docker compose down && docker compose up -d --build
```
