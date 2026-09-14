# HF Crawl — Docker Deployment

Portable, plug-n-play container for HF Crawl with web UI and Prometheus metrics.

## Quick Start

```bash
# Clone/copy the project
cd hf-crawl

# Set your HF token (optional)
export HF_TOKEN=hf_xxxxxxxxxxxx

# Run with docker compose
docker compose up -d

# Check status
docker compose ps
docker compose logs -f

# Open web UI: http://localhost:8501
# Metrics:     http://localhost:8000/metrics
```

## Using Docker CLI directly

```bash
# Build
docker build -t hf-crawl .

# Run (with data persistence + token)
docker run -d \
    --name hf-crawl \
    -e HF_TOKEN=hf_xxxxx \
    -v hf-crawl-data:/app/data \
    -v hf-crawl-logs:/app/logs \
    -p 8000:8000 \
    -p 8501:8501 \
    hf-crawl crawl

# Check metrics
curl http://localhost:8000/metrics | head

# Run 50-item smoke test
docker run --rm \
    -e HF_CRAWL_MAX_ITEMS=50 \
    -v hf-crawl-data:/app/data \
    -p 8000:8000 \
    hf-crawl crawl

# Start web UI only
docker run -d \
    --name hf-crawl-web \
    -v hf-crawl-data:/app/data \
    -p 8501:8501 \
    hf-crawl web

# Interactive shell
docker run -it --rm \
    -v hf-crawl-data:/app/data \
    hf-crawl shell
```

## Interactive commands (in running container)

```bash
# Open shell in running container
docker exec -it hf-crawl /bin/bash

# Run commands via entrypoint
docker exec hf-crawl hf-crawl list --max-items 100
docker exec hf-crawl hf-crawl info
docker exec hf-crawl hf-crawl card
docker exec hf-crawl hf-crawl test
docker exec hf-crawl hf-crawl metrics
docker exec hf-crawl hf-crawl version
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_TOKEN` | *(empty)* | Hugging Face API token (injected into requests) |
| `HF_CRAWL_ENV` | `dev` | `dev` or `prod` |
| `HF_CRAWL_CONFIG` | *auto* | Path to config YAML |
| `HF_CRAWL_MAX_ITEMS` | *(empty)* | Cap items per phase (testing) |
| `HF_CRAWL_PORT` | `8000` | Prometheus metrics port |
| `HF_CRAWL_WEB_PORT` | `8501` | Web UI port |

## Volumes

| Path | Purpose |
|------|---------|
| `/app/data` | DuckDB databases, checkpoints, JSONL archives |
| `/app/logs` | Structured JSON logs |

## Ports

| Port | Service |
|------|---------|
| 8000 | Prometheus `/metrics` endpoint |
| 8501 | Streamlit web UI |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Docker Container                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  HF Crawler (src/main.py)                            │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐             │   │
│  │  │ Phase 1 │→│ Phase 2 │→│ Phase 3 │             │   │
│  │  │ list    │  │ info    │  │ card    │             │   │
│  │  └─────────┘  └─────────┘  └─────────┘             │   │
│  └──────────────────────────────────────────────────────┘   │
│                           │                                  │
│              ┌────────────┼────────────┐                    │
│              ▼            ▼            ▼                    │
│     ┌──────────────┐ ┌────────┐ ┌──────────────┐          │
│     │  /metrics    │ │ DuckDB │ │  JSONL logs  │          │
│     │  port 8000   │ │ + chk  │ │              │          │
│     └──────────────┘ └────────┘ └──────────────┘          │
│              │                   │    │                    │
│              │                   │    │                    │
│  ┌───────────┴───────────────────┴────┴───────────────┐   │
│  │  Streamlit Web UI (port 8501)                      │   │
│  │  - Overview stats & charts                         │   │
│  │  - Browse models table                             │   │
│  │  - View model info & cards                         │   │
│  │  - Raw SQL query                                   │   │
│  └────────────────────────────────────────────────────┘   │
│                                                              │
│  Volumes:                                                    │
│    /app/data  →  DuckDB, checkpoints, archives              │
│    /app/logs  →  Structured JSON logs                       │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## How the HF Token is injected

1. You set `HF_TOKEN` in your environment or `.env` file
2. On container startup, entrypoint.sh runs:
   ```bash
   sed -i "s|\${HF_TOKEN}|${HF_TOKEN}|g" config.yaml
   ```
3. The crawler reads the now-populated token and includes it in requests:
   ```
   Authorization: Bearer hf_xxxxx
   ```
4. This gives you higher rate limits (1000 req/5min vs 500 anonymous)

## Monitoring Integration

```bash
# Prometheus scrape config (add to your prometheus.yml)
- job_name: "hf-crawl"
  scrape_interval: 10s
  static_configs:
    - targets: ["localhost:8000"]

# Grafana dashboard: import grafana/dashboard.json
# Alert rules:      copy hf_crawl_alerts.yml
# Loki logs:        configure promtail.yml → /app/logs
```

## Dockerfile Layers

```
python:3.12-slim
    │
    ├── apt-get install curl
    │
    ├── pip install -r requirements.txt
    │   (duckdb, httpx, pyyaml, prometheus_client, etc.)
    │
    ├── pip install -r web-requirements.txt
    │   (streamlit, pandas)
    │
    ├── COPY src/ config/ tests/ logs/
    ├── COPY grafana/ prometheus.yml loki.yml promtail.yml
    ├── COPY hf-crawl-web/app.py → /app/web/
    ├── COPY docker/entrypoint.sh docker/hf-crawl-docker.sh
    │
    ├── VOLUME ["/app/data", "/app/logs"]
    ├── EXPOSE 8000 8501
    │
    └── ENTRYPOINT ["/app/entrypoint.sh"]
```

## Convenience wrapper (host machine)

Place `docker/hf-crawl-docker.sh` on your PATH:

```bash
# Build
hf-crawl-docker build

# Start
HF_TOKEN=hf_xxx hf-crawl-docker start

# Check
hf-crawl-docker status
hf-crawl-docker metrics

# Run phases
hf-crawl-docker list
hf-crawl-docker info
hf-crawl-docker card

# Web UI
hf-crawl-docker web

# Cleanup
hf-crawl-docker cleanup
```

## Troubleshooting

### Container won't start
```bash
docker compose logs hf-crawl
docker run --rm -it hf-crawl shell  # debug inside
```

### No metrics
```bash
curl http://localhost:8000/metrics
# Check logs:
docker compose logs hf-crawl | grep -i error
```

### Web UI not loading
```bash
# Check if streamlit is running
docker exec hf-crawl ps aux | grep streamlit

# Start web manually
docker exec -d hf-crawl hf-crawl web
```

### Data not persisting
```bash
# Check volume
docker volume inspect hf-crawl-data

# Verify mount
docker exec hf-crawl ls -la /app/data/
```

### HF Token not working
```bash
# Verify it's set
docker exec hf-crawl env | grep HF_TOKEN

# Check config was updated
docker exec hf-crawl cat /app/config/config.dev.yaml | grep token
```
