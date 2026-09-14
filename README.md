# HF Crawl

Fetch and store model cards for all public models on Hugging Face Hub.

A portable, self-contained system that crawls ~1.8–2 million models in three phases: **list** → **info** → **card**. Data is stored in DuckDB with JSONL archive backup. Includes a web UI, Prometheus metrics, and full Docker support.

## Features

- **3-phase pipeline**: List models → Fetch info → Fetch README cards
- **Resumable**: Per-phase checkpoints, crash-safe with automatic resume
- **Rate-limit aware**: Conservative async requests with exponential backoff
- **Observable**: Prometheus metrics on `:8000`, structured JSON logs
- **Web UI**: Streamlit dashboard to browse models, info, and cards
- **Portable**: Single Docker container, plug-n-play with volume mounts
- **Configurable**: Environment variables, YAML configs, CLI flags

---

## Quick Start

### Option A: Local (Python 3.12+)

```bash
# Clone the repo
git clone <repo-url> && cd hf-crawl

# Create virtual environment
python3 -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run 50-item smoke test (anonymous)
python -m src.main --phase all --max-items 50 --config config/config.dev.yaml

# Start web UI
cd ../hf-crawl-web && source .venv/bin/activate
streamlit run app.py --server.port 8501
```

### Option B: Docker (Recommended)

```bash
# Build and run with Docker Compose
HF_TOKEN=hf_xxxxxxxxxxxx docker compose up -d

# Or with Docker directly
docker build -t hf-crawl .
docker run -d \
    --name hf-crawl \
    -e HF_TOKEN=hf_xxxxxxxxxxxx \
    -v hf-crawl-data:/app/data \
    -p 8000:8000 \
    -p 8501:8501 \
    hf-crawl crawl

# View logs
docker logs -f hf-crawl

# Open web UI: http://localhost:8501
# Metrics:     http://localhost:8000/metrics
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           HF Crawl System                               │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        CLI Entry Point                           │   │
│  │                    (src/main.py → click)                         │   │
│  └───────────────────────────────┬─────────────────────────────────┘   │
│                                  │                                      │
│  ┌───────────────────────────────▼─────────────────────────────────┐   │
│  │                        Orchestrator                              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │ PhaseGovernor│  │ SignalHandler│  │  HealthChecker       │  │   │
│  │  │ (thresholds) │  │ (SIGINT/TERM)│  │  (DB/disk/API)       │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  └───────────────────────────────┬─────────────────────────────────┘   │
│                                  │                                      │
│  ┌───────────────────────────────▼─────────────────────────────────┐   │
│  │                     Phase Implementations                        │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │  Phase 1     │  │  Phase 2     │  │  Phase 3             │  │   │
│  │  │  list        │→ │  info        │→ │  card                │  │   │
│  │  │  (cursor     │  │  (per-model  │  │  (README + YAML)     │  │   │
│  │  │  pagination) │  │  fetch)      │  │                      │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  └───────────────────────────────┬─────────────────────────────────┘   │
│                                  │                                      │
│  ┌───────────────────────────────▼─────────────────────────────────┐   │
│  │                       Core Components                            │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │   │
│  │  │ Fetcher  │  │ Storage  │  │Checkpoint│  │ RateLimiter  │   │   │
│  │  │ (httpx)  │  │ (DuckDB) │  │ (JSON)   │  │ (token bucket│   │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       Outputs                                    │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │   │
│  │  │  DuckDB      │  │  JSONL       │  │  Prometheus          │  │   │
│  │  │  database    │  │  archives    │  │  /metrics            │  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Phases

| Phase | What | Endpoint | Output Table |
|-------|------|----------|--------------|
| 1 — List | Cursor pagination over `/api/models` | `GET /api/models?sort=createdAt&direction=1` | `models_list` |
| 2 — Info | Per-model metadata | `GET /api/models/{id}` | `model_info` |
| 3 — Card | README.md content | `GET /{id}/raw/main/README.md` | `model_card` |

### Phase Gating

- **Phase 2** starts automatically when Phase 1 reaches 25% (configurable)
- **Phase 3** starts when Phase 1 and Phase 2 are both 100% complete

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_TOKEN` | *(empty)* | Hugging Face API token (higher rate limits) |
| `HF_CRAWL_ENV` | `dev` | `dev` or `prod` |
| `HF_CRAWL_CONFIG` | *auto* | Path to config YAML |
| `HF_CRAWL_MAX_ITEMS` | *(empty)* | Cap items per phase (for testing) |
| `HF_CRAWL_PORT` | `8000` | Prometheus metrics port |
| `HF_CRAWL_WEB_PORT` | `8501` | Web UI port |

### Config Files

```yaml
# config/config.dev.yaml
environment: dev

huggingface:
  token: "${HF_TOKEN}"          # Set via env var, injected at runtime
  base_url: "https://huggingface.co"
  sort_field: "createdAt"        # Immutable — stable paging
  sort_direction: 1              # Ascending
  page_size: 1000               # HF API max

rate_limiting:
  max_requests_per_second: 3     # Conservative for anonymous
  max_concurrent_requests: 5
  max_retries: 5
  backoff_base_seconds: 1.0
  backoff_max_seconds: 60.0

phase_gating:
  phase2_start_threshold_pct: 25 # Start info crawl at 25% of list
  phase3_start_threshold_pct: 100 # Start card crawl at 100% of info

storage:
  duckdb_path: "./data/dev/model_cards.duckdb"
  jsonl_archive_dir: "./data/dev/archive"

checkpoint:
  dir: "./data/dev/checkpoint"
  save_every_n_pages: 1

logging:
  level: "INFO"
  file: "./logs/dev.log"
  progress_every_n_models: 100

metrics:
  enabled: true
  port: 8000
```

### Database Schema

```sql
-- Phase 1 output
CREATE TABLE models_list (
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

-- Phase 2 output
CREATE TABLE model_info (
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

-- Phase 3 output
CREATE TABLE model_card (
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
```

---

## CLI Usage

```bash
# Development: 50-item smoke test
python -m src.main --phase all --max-items 50 --config config/config.dev.yaml

# Development: 500-item test
python -m src.main --phase all --max-items 500 --config config/config.dev.yaml

# Production: smoke test
python -m src.main --phase list --max-items 50 --config config/config.prod.yaml

# Production: full crawl (all phases)
python -m src.main --phase all --config config/config.prod.yaml

# Run single phase
python -m src.main --phase list --config config/config.prod.yaml
python -m src.main --phase info --config config/config.prod.yaml
python -m src.main --phase card --config config/config.prod.yaml

# Resume (automatic — checks checkpoint)
python -m src.main --phase list --config config/config.prod.yaml
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `--phase {all,list,info,card}` | Which phase(s) to run |
| `--max-items N` | Cap items per phase (for testing) |
| `--config PATH` | Path to config YAML |

---

## Docker Deployment

### Quick Start

```bash
# Build
docker build -t hf-crawl .

# Run with token + data persistence
docker run -d \
    --name hf-crawl \
    -e HF_TOKEN=*** \
    -e HF_CRAWL_MAX_ITEMS=50 \
    -v hf-crawl-data:/app/data \
    -v hf-crawl-logs:/app/logs \
    -p 8000:8000 \
    -p 8501:8501 \
    hf-crawl crawl
```

### Docker Compose

```bash
# Set your token
export HF_TOKEN=***

# Start crawler
docker compose up -d

# Start with monitoring stack (Prometheus + Grafana + Loki)
docker compose -f docker-compose.monitoring.yml up -d

# View logs
docker compose logs -f

# Stop
docker compose down

# Stop and remove volumes
docker compose down -v
```

### Interacting with a Running Container

```bash
# Open shell inside container
docker exec -it hf-crawl /bin/bash

# Run commands via entrypoint
docker exec hf-crawl hf-crawl list --max-items 100
docker exec hf-crawl hf-crawl info
docker exec hf-crawl hf-crawl card
docker exec hf-crawl hf-crawl test
docker exec hf-crawl hf-crawl metrics
docker exec hf-crawl hf-crawl version

# Start web UI inside running container
docker exec -d hf-crawl hf-crawl web

# Check metrics
curl http://localhost:8000/metrics | grep "^# HELP"
```

### Docker Volumes

| Mount | Contents |
|-------|----------|
| `/app/data` | DuckDB databases, checkpoints, JSONL archives |
| `/app/logs` | Structured JSON logs |

### Docker Ports

| Port | Service |
|------|---------|
| 8000 | Prometheus `/metrics` endpoint |
| 8501 | Streamlit web UI |

---

## Web UI Dashboard

Streamlit-based browser interface to explore the crawled data.

```bash
# Local
cd hf-crawl-web
pip install -r requirements.txt
streamlit run app.py --server.port 8501

# Docker
docker exec -d hf-crawl hf-crawl web
# → http://localhost:8501
```

### Pages

| Page | What it shows |
|------|---------------|
| **Overview** | DB stats, pipeline tag bar chart, top 20 by downloads |
| **Models** | Searchable/filterable table of all models |
| **Model Info** | Detailed info (SHA, gated, siblings, config, card data) |
| **Model Card** | README markdown render + YAML metadata |
| **Raw SQL** | Run arbitrary SQL against DuckDB |

---

## Monitoring & Observability

HF Crawl exposes Prometheus metrics on port 8000.

### Metrics Exposed

| Type | Metric | Labels |
|------|--------|--------|
| Counter | `hf_crawl_models_fetched_total` | `phase`, `status` |
| Counter | `hf_crawl_requests_total` | `endpoint`, `status_code` |
| Counter | `hf_crawl_rate_limit_hits_total` | `endpoint` |
| Gauge | `hf_crawl_phase_progress_pct` | `phase` |
| Gauge | `hf_crawl_phase_status` | `phase` |
| Gauge | `hf_crawl_rate_limit_remaining` | `bucket` |
| Gauge | `hf_crawl_db_size_bytes` | — |
| Gauge | `hf_crawl_disk_free_bytes` | — |
| Gauge | `hf_crawl_active_workers` | `phase` |
| Gauge | `hf_crawl_throughput_models_per_second` | `phase` |
| Histogram | `hf_crawl_request_duration_seconds` | `endpoint`, `status_code` |
| Histogram | `hf_crawl_batch_commit_duration_seconds` | `phase` |

### Prometheus Integration

```yaml
# Add to prometheus.yml
scrape_configs:
  - job_name: "hf-crawl"
    scrape_interval: 10s
    static_configs:
      - targets: ["localhost:8000"]
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: "hf_crawl_.*"
        action: keep
```

### Grafana Dashboard

```bash
# Import grafana/dashboard.json into Grafana
# Or use Docker Compose monitoring stack:
docker compose -f docker-compose.monitoring.yml up -d
# Grafana: http://localhost:3000 (admin/admin)
```

### Alert Rules

| Alert | Condition | Severity |
|-------|-----------|----------|
| `HighRateLimitHits` | `rate(hf_crawl_rate_limit_hits_total[5m]) > 5` | warning |
| `LowDiskSpace` | `hf_crawl_disk_free_bytes < 10GB` | critical |
| `PhaseStuck` | `delta(hf_crawl_phase_progress_pct[30m]) == 0` | warning |
| `HighErrorRate` | `rate(hf_crawl_models_fetched_total{status="error"}[5m]) > 0.1` | warning |
| `CrawlDown` | `up{job="hf-crawl"} == 0` | critical |

### Loki Integration

```bash
# Start Loki + Promtail
docker compose -f docker-compose.monitoring.yml up -d

# Query logs in Grafana Explore:
{job="hf-crawl"} |= "phase1"
{job="hf-crawl", level="error"}
{job="hf-crawl", phase="list"} | json
```

---

## Testing

```bash
# Activate venv
source .venv/bin/activate

# Smoke tests (50 items) — ~40s
python -m pytest tests/test_smoke.py -v

# Integration tests — ~70s
python -m pytest tests/test_integration.py -v

# Dev tests (500 items) — ~6 min
python -m pytest tests/test_dev.py -v

# All tests
python -m pytest tests/ -v
```

---

## Project Structure

```
hf-crawl/
├── README.md                    # This file
├── ACTION_PLAN.md               # Original project plan
├── DOCKER.md                    # Docker deployment guide
├── MONITORING.md                # Observability guide
├── Dockerfile                   # Container image definition
├── docker-compose.yml           # Single-container deployment
├── docker-compose.monitoring.yml # Full monitoring stack
├── .env.example                 # Environment variable template
├── .dockerignore
├── .gitignore
│
├── config/
│   ├── config.dev.yaml          # Development config
│   └── config.prod.yaml         # Production config
│
├── src/
│   ├── main.py                  # CLI entry point (click)
│   ├── config.py                # Config loader + logging setup
│   ├── metrics.py               # Prometheus metric definitions
│   ├── utils.py                 # Helpers (timestamps, hashing, YAML)
│   ├── orchestrator.py          # PhaseGovernor, SignalHandler, HealthChecker, MetricsServer, ProgressTracker, Orchestrator
│   │
│   ├── phases/
│   │   ├── base.py              # Abstract phase class (future)
│   │   ├── phase1_list.py       # Cursor pagination over /api/models
│   │   ├── phase2_info.py       # Per-model info fetch
│   │   └── phase3_card.py       # README fetch + YAML parse
│   │
│   └── components/
│       ├── fetcher.py           # Async HTTP client with retries
│       ├── rate_limiter.py      # Token bucket + semaphore
│       ├── checkpoint.py        # Per-phase JSON checkpoints
│       ├── storage.py           # DuckDB UPSERT + JSONL archive
│       └── parser.py            # Response parsers (list, info, card)
│
├── tests/
│   ├── conftest.py              # Pytest fixtures (temp dirs, configs)
│   ├── test_smoke.py            # 50-item tests (3 tests)
│   ├── test_integration.py      # Pipeline + resume tests (2 tests)
│   └── test_dev.py              # 500-item tests (2 tests)
│
├── grafana/
│   └── dashboard.json           # 13-panel Grafana dashboard
│
├── prometheus.yml               # Scrape config + alert rules
├── hf_crawl_alerts.yml          # 5 alert rules
├── loki.yml                     # Loki log aggregation config
├── promtail.yml                 # Promtail log shipping config
│
├── data/
│   ├── dev/                     # Development data
│   │   ├── model_cards.duckdb   # DuckDB database
│   │   ├── archive/             # Compressed JSONL archives
│   │   └── checkpoint/          # Per-phase checkpoint files
│   └── prod/                    # Production data (same structure)
│
├── logs/
│   ├── dev.log                  # Development logs
│   └── prod.log                 # Production logs
│
├── hf-crawl-web/
│   ├── app.py                   # Streamlit web UI
│   └── requirements.txt         # Web UI dependencies
│
└── docker/
    ├── entrypoint.sh            # Container entrypoint with CLI routing
    └── hf-crawl-docker.sh       # Host convenience wrapper
```

---

## Troubleshooting

### No data in database
```bash
# Check logs
tail -20 logs/dev.log

# Verify API is reachable
curl -s "https://huggingface.co/api/models?limit=1" | head -c 500

# Check checkpoints
ls -la data/dev/checkpoint/phase1_list/
```

### Rate limit hits
```bash
# Add HF_TOKEN for higher limits
export HF_TOKEN=hf_***

# Or reduce rate in config
rate_limiting:
  max_requests_per_second: 2  # Lower from 3
```

### Container crashes
```bash
docker logs hf-crawl  # Check container logs
docker run --rm -it hf-crawl shell  # Debug inside
```

### Web UI not loading
```bash
# Check if Streamlit is running
docker exec hf-crawl ps aux | grep streamlit

# Start web manually
docker exec -d hf-crawl hf-crawl web
```

### Prometheus not scraping
```bash
# Check metrics endpoint
curl http://localhost:8000/metrics

# Check Prometheus targets
open http://localhost:9090/targets
```

---

## Requirements

| Requirement | Minimum |
|-------------|---------|
| Python | 3.12+ |
| RAM | 4 GB |
| Disk | 100 GB free |
| Network | Stable internet |
| OS | Linux (tested on 64.8 kernel), macOS, Windows |

## Cost Estimation

| Resource | Cost |
|----------|------|
| Hugging Face PRO (optional) | ~$9/month |
| Compute (local) | $0 |
| Storage (100 GB local) | $0 |
| **Total** | **$0–9/month** |

---

## License

Research/internal use. Data is public from Hugging Face. Give attribution to HF.

---

## Roadmap

- [ ] Incremental updates (lastModified polling)
- [ ] Incremental card updates (ETag-based)
- [ ] Export to Parquet/CSV
- [ ] Full-text search on README content
- [ ] Model similarity/search index
