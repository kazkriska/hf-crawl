# HF Crawl — Final Action Plan

**Project:** Hugging Face Hub Model Card Crawl  
**Location:** Projects/hf-crawl/  
**Author:** CTO (Kevin) + Data Engineer  
**Status:** Approved — Ready for Implementation  
**Last Updated:** 2026-09-13  

---

## 1. Project Summary

Build a system to fetch and store model cards for all ~1.8–2 million public models on Hugging Face Hub. The crawl runs in three phases: list all models, fetch model info, fetch model cards. Each phase stores data in a separate, linked table. The system uses an orchestrator for phase gating, Prometheus for metrics, and Grafana for dashboards. Development and production use separate database files.

---

## 2. Architecture Decisions (Final)

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Sort parameter | `createdAt` ascending | Immutable — order never shifts mid-crawl |
| 2 | Pipeline | 3 phases: list → info → card | Separation of concerns, parallelizable, re-runnable |
| 3 | DB engine | DuckDB | Single-file, columnar, compressed, fast analytics |
| 4 | Tables | 3 tables with FK chain | Normalized, no sparse columns, clean joins |
| 5 | Phase gating | Phase 2 at X%, Phase 3 at 100% | Early info crawl, but cards only after full info |
| 6 | Orchestrator | Central coordinator | Single entry point, signal handling, metrics, health |
| 7 | Concurrency | Asyncio, semaphore-controlled | I/O bound, single IP, safe for HF rate limits |
| 8 | Metrics | Prometheus `/metrics` endpoint | Integrates with existing Grafana server |
| 9 | Dev/Prod isolation | Separate DB files | Clean slate for prod, test data never pollutes |
| 10 | Testing | Smoke (50 items) + Dev (500 items) | Full code path verification before prod |
| 11 | Incremental updates | `lastModified` polling + ETag | Post-crawl freshness without full re-crawl |
| 12 | Resumability | Per-phase checkpoints | Re-runnable after crashes, no duplicate work |

---

## 3. Database Schema

### 3.1 `models_list` (Phase 1)

```sql
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
```

### 3.2 `model_info` (Phase 2)

```sql
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
```

### 3.3 `model_card` (Phase 3)

```sql
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

## 4. Prometheus Metrics

### 4.1 Counters (Ever-Increasing)

| Metric | Labels | Description |
|---|---|---|
| `hf_crawl_models_fetched_total` | `phase`, `status` | Total models fetched |
| `hf_crawl_requests_total` | `endpoint`, `status_code` | Total HTTP requests |
| `hf_crawl_rate_limit_hits_total` | `endpoint` | Total 429 responses |

### 4.2 Gauges (Up/Down)

| Metric | Labels | Description |
|---|---|---|
| `hf_crawl_phase_progress_pct` | `phase` | Current phase progress % |
| `hf_crawl_phase_status` | `phase` | 0=pending, 1=running, 2=complete, 3=failed |
| `hf_crawl_rate_limit_remaining` | `bucket` | Remaining requests in window |
| `hf_crawl_db_size_bytes` | — | Database file size |
| `hf_crawl_disk_free_bytes` | — | Free disk space |
| `hf_crawl_active_workers` | `phase` | Active async workers |
| `hf_crawl_throughput_models_per_second` | `phase` | Current crawl speed |

### 4.3 Histograms (Distributions)

| Metric | Labels | Description |
|---|---|---|
| `hf_crawl_request_duration_seconds` | `endpoint`, `status_code` | HTTP latency |
| `hf_crawl_batch_commit_duration_seconds` | `phase` | DB commit time |

---

## 5. Grafana Dashboard

### 5.1 Panels Required

| Panel | Type | Metrics |
|---|---|---|
| Phase Progress | Gauge (x3) | `phase_progress_pct` |
| Phase Status | Stat | `phase_status` |
| Throughput | Time Series | `models_per_second` |
| Total Fetched | Counter | `models_fetched_total` |
| Request Rate | Time Series | `requests_total` by `status_code` |
| Rate Limit Remaining | Gauge | `current_rate_limit_remaining` |
| Request Latency | Heatmap | `request_duration_seconds` |
| DB Size | Time Series | `db_size_bytes` |
| Disk Space | Gauge | `disk_free_bytes` |
| Active Workers | Time Series | `active_workers` |
| Error Rate | Time Series | `rate_limit_hits_total` |

### 5.2 Alert Rules

| Alert | Condition | Severity |
|---|---|---|
| HighRateLimitHits | `rate(rate_limit_hits_total[5m]) > 5` | warning |
| LowDiskSpace | `disk_free_bytes < 10GB` | critical |
| PhaseStuck | `delta(phase_progress_pct[30m]) == 0` | warning |

---

## 6. Project Structure

```
Projects/hf-crawl/
├── README.md                    # Project overview
├── ACTION_PLAN.md               # This file
├── config/
│   ├── config.dev.yaml          # Development config
│   └── config.prod.yaml         # Production config
├── data/
│   ├── dev/
│   │   ├── model_cards.duckdb   # Dev database
│   │   ├── checkpoint/          # Dev checkpoints
│   │   └── archive/             # Dev JSONL archive
│   └── prod/
│       ├── model_cards.duckdb   # Prod database
│       ├── checkpoint/          # Prod checkpoints
│       └── archive/             # Prod JSONL archive
├── src/
│   ├── main.py                  # CLI entry point
│   ├── orchestrator.py          # Phase governor, signal handler, metrics
│   ├── config.py                # Config loader
│   ├── phases/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract phase class
│   │   ├── phase1_list.py       # List fetcher
│   │   ├── phase2_info.py       # Info fetcher
│   │   └── phase3_card.py       # Card fetcher
│   ├── components/
│   │   ├── __init__.py
│   │   ├── fetcher.py           # HTTP client with rate limiting
│   │   ├── parser.py            # YAML/data parser
│   │   ├── checkpoint.py        # Checkpoint manager
│   │   ├── storage.py           # DuckDB + JSONL writer
│   │   └── rate_limiter.py      # Token-bucket rate limiter
│   ├── metrics.py               # Prometheus metrics definitions
│   └── utils.py                 # Helpers, logging
├── tests/
│   ├── test_smoke.py            # 50-item smoke tests
│   ├── test_dev.py              # 500-item dev tests
│   ├── test_integration.py      # Full pipeline test
│   └── conftest.py              # Test fixtures
├── logs/
│   ├── dev.log
│   └── prod.log
├── grafana/
│   └── dashboard.json           # Grafana dashboard export
├── prometheus.yml               # Prometheus scrape config snippet
└── requirements.txt             # Python dependencies
```

---

## 7. Configuration Files

### 7.1 `config/config.dev.yaml`

```yaml
environment: dev

huggingface:
  token: "${HF_TOKEN}"
  base_url: "https://huggingface.co"
  sort_field: "createdAt"
  sort_direction: 1
  page_size: 1000

rate_limiting:
  max_requests_per_second: 3
  max_concurrent_requests: 5
  max_retries: 5
  backoff_base_seconds: 1.0
  backoff_max_seconds: 60.0

phase_gating:
  phase2_start_threshold_pct: 25
  phase3_start_threshold_pct: 100

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

### 7.2 `config/config.prod.yaml`

```yaml
environment: prod

huggingface:
  token: "${HF_TOKEN}"
  base_url: "https://huggingface.co"
  sort_field: "createdAt"
  sort_direction: 1
  page_size: 1000

rate_limiting:
  max_requests_per_second: 3
  max_concurrent_requests: 5
  max_retries: 5
  backoff_base_seconds: 1.0
  backoff_max_seconds: 60.0

phase_gating:
  phase2_start_threshold_pct: 25
  phase3_start_threshold_pct: 100

storage:
  duckdb_path: "./data/prod/model_cards.duckdb"
  jsonl_archive_dir: "./data/prod/archive"

checkpoint:
  dir: "./data/prod/checkpoint"
  save_every_n_pages: 1

logging:
  level: "INFO"
  file: "./logs/prod.log"
  progress_every_n_models: 1000

metrics:
  enabled: true
  port: 8000
```

---

## 8. CLI Interface

```bash
# Development: full verification with 500 items
python src/main.py --phase all --max-items 500 --config config/config.dev.yaml

# Development: smoke test with 50 items
python src/main.py --phase all --max-items 50 --config config/config.dev.yaml

# Production: smoke test with 50 items
python src/main.py --phase list --max-items 50 --config config/config.prod.yaml

# Production: full list crawl (after smoke test passes)
python src/main.py --phase list --config config/config.prod.yaml

# Production: run info phase (when list hits threshold)
python src/main.py --phase info --config config/config.prod.yaml

# Production: run card phase (when info is 100%)
python src/main.py --phase card --config config/config.prod.yaml

# Resume after crash (automatic — loads checkpoint)
python src/main.py --phase list --config config/config.prod.yaml
```

---

## 9. Phase Gating Logic

```
START
  │
  ▼
┌─────────────────────┐
│ Phase 1: LIST       │
│ - createdAt asc     │
│ - Cursor pagination │
│ - Page size: 1000   │
│ - Checkpoint: page  │
└──────────┬──────────┘
           │
           │ When Phase 1 ≥ 25%:
           ▼
┌─────────────────────┐     ┌─────────────────────┐
│ Phase 1: LIST       │     │ Phase 2: INFO       │
│ (continues to 100%)  │     │ - Per-model fetch   │
│                     │◄────│ - FK to models_list │
└──────────┬──────────┘     │ - Checkpoint: model │
           │                └──────────┬──────────┘
           │                           │
           │                           │ When Phase 2 = 100%:
           │                           ▼
           │                ┌─────────────────────┐
           │                │ Phase 3: CARD       │
           │                │ - README.md fetch   │
           │                │ - YAML parse        │
           │                │ - FK to models_list │
           │                └─────────────────────┘
           │
           ▼
       COMPLETE
```

---

## 10. Rate Limiting Strategy

### 10.1 Rate Limits (Per 5-Minute Window)

| Plan | API | Resolvers | Pages |
|---|---|---|---|
| Anonymous | 500 | 3,000 | 100 |
| Free | 1,000 | 5,000 | 200 |
| PRO | 2,500 | 12,000 | 400 |
| Enterprise | 6,000 | 50,000 | 600 |

### 10.2 Safe Rates

| Target | Rate | Rationale |
|---|---|---|
| Phase 1 (API) | 2–3 req/sec | Conservative, allows headroom |
| Phase 2 (API) | 2–3 req/sec | Same bucket as Phase 1 |
| Phase 3 (Resolvers) | 10–20 req/sec | Resolver bucket is 5–10x higher |
| Max concurrent | 5 workers | Prevents connection exhaustion |

### 10.3 Retry Strategy

| Status | Action |
|---|---|
| 429 | Parse `RateLimit` header → wait exact seconds → retry |
| 5xx | Exponential backoff (1s, 2s, 4s, 8s, max 60s) + jitter |
| 404 | Mark as deleted, skip |
| 403 | Mark as gated/private, skip |
| Timeout | Retry up to 3 times, then mark as failed |
| Connection reset | Retry with backoff |

**Max retries:** 5 per request before permanent failure.

---

## 11. Checkpoint & Resume

### 11.1 Checkpoint Files

```
checkpoint/
├── phase1_list/
│   ├── state.json          # Cursor, page, count
│   └── failed_models.json  # Failed IDs for retry
├── phase2_info/
│   ├── state.json          # Last model_id, count
│   └── failed_models.json
└── phase3_card/
    ├── state.json
    └── failed_models.json
```

### 11.2 Resume Logic

1. On startup, check for existing checkpoint
2. If exists → resume from cursor/last_model_id
3. If not → start from beginning
4. UPSERT ensures re-running doesn't create duplicates
5. `last_modified` / ETag checks skip unchanged models

---

## 12. Anti-Spam / ToS Compliance

### 12.1 Required Practices

- ✅ Always pass `HF_TOKEN` (free account token is sufficient)
- ✅ Use descriptive `User-Agent` header
- ✅ Respect `RateLimit` HTTP headers
- ✅ Implement exponential backoff with jitter
- ✅ Single IP, no distributed crawling
- ✅ Conservative request rates (2–3 req/sec for API)

### 12.2 ToS Analysis

- Model cards are **public** and intended for discovery
- HF's ToS does **not** explicitly prohibit API-based data collection
- Must comply with export control laws
- Cannot use to build competing model hosting platform
- Must respect rate limits and authentication requirements
- Recommendation: Store for research/internal use only; give attribution to HF

---

## 13. Storage Estimation

| Component | Calculation | Size |
|---|---|---|
| models_list (1.8M rows) | ~3 KB avg | ~5.4 GB |
| model_info (1.8M rows) | ~5 KB avg | ~9.0 GB |
| model_card (1.8M rows) | ~20 KB avg | ~36.0 GB |
| **Total raw** | | **~50.4 GB** |
| DuckDB compression | 50–60% | ~25–30 GB |
| JSONL archive (compressed) | | ~20–25 GB |
| **Total with overhead** | | **~50–60 GB** |

**Recommendation:** Ensure **100 GB free** on target disk.

---

## 14. Cost Estimation

| Resource | Cost |
|---|---|
| Hugging Face PRO (optional) | ~$9/month |
| Compute (local machine) | $0 |
| Storage (100 GB local) | $0 |
| **Total** | **$0–9/month** |

---

## 15. Task List

### Phase 0: Project Setup

| ID | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 0.1 | Create project directory structure | ⬜ | Kevin | |
| 0.2 | Set up Python virtual environment | ⬜ | Kevin | Python 3.12+, uv or venv |
| 0.3 | Create `requirements.txt` | ⬜ | Kevin | duckdb, httpx, pyyaml, prometheus_client |
| 0.4 | Create `config/config.dev.yaml` | ⬜ | Kevin | |
| 0.5 | Create `config/config.prod.yaml` | ⬜ | Kevin | |
| 0.6 | Create `.gitignore` (data/, logs/, __pycache__) | ⬜ | Kevin | |
| 0.7 | Create `README.md` | ⬜ | Kevin | Project overview |

### Phase 1: Core Components

| ID | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 1.1 | Implement `Config` loader class | ⬜ | Kevin | YAML + env vars + CLI flags |
| 1.2 | Implement `Fetcher` HTTP client | ⬜ | Kevin | httpx async, auth headers, retries |
| 1.3 | Implement `RateLimiter` | ⬜ | Kevin | Token bucket, adaptive backoff |
| 1.4 | Implement `CheckpointManager` | ⬜ | Kevin | Load/save JSON, per-phase |
| 1.5 | Implement `Storage` writer | ⬜ | Kevin | DuckDB UPSERT, JSONL append |
| 1.6 | Implement `Parser` utilities | ⬜ | Kevin | YAML parsing, validation, hashing |
| 1.7 | Implement `Logger` setup | ⬜ | Kevin | Structured JSON, phase context |
| 1.8 | Implement `Metrics` definitions | ⬜ | Kevin | All counters, gauges, histograms |

### Phase 2: Orchestrator

| ID | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 2.1 | Implement `Orchestrator` class | ⬜ | Kevin | Main loop, phase management |
| 2.2 | Implement `PhaseGovernor` | ⬜ | Kevin | Threshold checking, phase triggers |
| 2.3 | Implement `SignalHandler` | ⬜ | Kevin | SIGINT/SIGTERM → save checkpoints |
| 2.4 | Implement `HealthChecker` | ⬜ | Kevin | DB, API, disk space checks |
| 2.5 | Implement `MetricsServer` | ⬜ | Kevin | `/metrics` HTTP endpoint |
| 2.6 | Implement `ProgressTracker` | ⬜ | Kevin | %, ETA, throughput |

### Phase 3: Phase Implementations

| ID | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 3.1 | Implement `Phase1ListModelFetcher` | ⬜ | Kevin | Cursor pagination, createdAt sort |
| 3.2 | Implement `Phase2ModelInfoFetcher` | ⬜ | Kevin | Per-model, FK to models_list |
| 3.3 | Implement `Phase3ModelCardFetcher` | ⬜ | Kevin | README + YAML, FK to models_list |
| 3.4 | Wire phases into Orchestrator | ⬜ | Kevin | Phase gating logic |

### Phase 4: Testing

| ID | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 4.1 | Create test fixtures and conftest.py | ⬜ | Kevin | |
| 4.2 | Write smoke test (50 items) | ⬜ | Kevin | All 3 phases |
| 4.3 | Write dev test (500 items) | ⬜ | Kevin | All 3 phases |
| 4.4 | Write integration test (full pipeline) | ⬜ | Kevin | Phase gating + resume |
| 4.5 | Run smoke test in dev | ⬜ | Kevin | Verify 50 items work |
| 4.6 | Run dev test in dev | ⬜ | Kevin | Verify 500 items work |
| 4.7 | Fix any bugs from tests | ⬜ | Kevin | |

### Phase 5: Deployment

| ID | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 5.1 | Run production smoke test (50 items) | ⬜ | Kevin | `config/config.prod.yaml` |
| 5.2 | Verify prod smoke test results | ⬜ | Kevin | Check DB, checkpoints, logs |
| 5.3 | Remove `--max-items` cap | ⬜ | Kevin | |
| 5.4 | Start full production crawl | ⬜ | Kevin | Phase 1 only initially |
| 5.5 | Monitor Grafana dashboard | ⬜ | Kevin | Verify metrics flowing |
| 5.6 | Verify phase 1 completion | ⬜ | Kevin | |
| 5.7 | Start phase 2 (info) | ⬜ | Kevin | |
| 5.8 | Verify phase 2 completion | ⬜ | Kevin | |
| 5.9 | Start phase 3 (card) | ⬜ | Kevin | |
| 5.10 | Verify phase 3 completion | ⬜ | Kevin | |

### Phase 6: Monitoring & Maintenance

| ID | Task | Status | Owner | Notes |
|---|---|---|---|---|
| 6.1 | Set up Prometheus scrape config | ⬜ | Kevin | `prometheus.yml` → localhost:8000 |
| 6.2 | Import Grafana dashboard | ⬜ | Kevin | `grafana/dashboard.json` |
| 6.3 | Configure Grafana alerts | ⬜ | Kevin | Rate limit, disk, stuck phase |
| 6.4 | Implement incremental update script | ⬜ | Kevin | `lastModified` + ETag |
| 6.5 | Schedule daily incremental run | ⬜ | Kevin | cron or systemd timer |
| 6.6 | Set up log rotation | ⬜ | Kevin | Prevent disk fill |
| 6.7 | Document runbook | ⬜ | Kevin | What breaks, how to fix, who to call |

---

## 16. Dependencies

### Python Packages

```txt
# requirements.txt
duckdb>=1.0.0
httpx>=0.27.0
pyyaml>=6.0
prometheus_client>=0.20.0
pydantic>=2.0  # Config validation
structlog>=24.0  # Structured logging
tenacity>=8.0  # Retry logic (or custom)
click>=8.0  # CLI framework
```

### System Requirements

| Requirement | Minimum |
|---|---|
| Python | 3.12+ |
| RAM | 4 GB |
| Disk | 100 GB free |
| Network | Stable internet connection |
| OS | Linux (tested on 6.8 kernel) |

---

## 17. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| HF changes API | Low | High | Abstract fetcher; easy to adapt |
| Rate limit ban | Low | Medium | Conservative rates, backoff, auth token |
| Disk full | Medium | High | Monitor disk, alert at 10 GB free |
| Network outage | Medium | Low | Auto-resume from checkpoint |
| DB corruption | Low | High | JSONL archive as backup |
| Code bug mid-crawl | Medium | Medium | Dev testing, idempotent UPSERTs |
| HF ToS change | Low | High | Stay updated; data is public/research |

---

## 18. Success Criteria

| Criterion | Target |
|---|---|
| Phase 1 completion | 100% of models_list table populated |
| Phase 2 completion | 100% of model_info table populated |
| Phase 3 completion | 100% of model_card table populated |
| FK integrity | All info/card rows have valid list reference |
| Data quality | >99.9% fetch success rate |
| No rate limit bans | Zero IP-level bans |
| Monitoring | Grafana dashboard fully functional |
| Incremental updates | Daily delta crawl completes in <1 hour |

---

## 19. Timeline Estimate

| Phase | Duration | Notes |
|---|---|---|
| Setup + Core Components | 1–2 days | Config, fetcher, storage, metrics |
| Orchestrator | 1 day | Phase gating, signal handling |
| Phase Implementations | 2–3 days | All 3 phases wired up |
| Testing | 1–2 days | Smoke, dev, integration |
| Production Deployment | 1 day | Smoke test → full crawl |
| Monitoring Setup | 0.5 day | Prometheus, Grafana, alerts |
| **Total Development** | **6–9 days** | |
| Phase 1 crawl (prod) | ~4 days | ~3 req/sec, 1.8M models |
| Phase 2 crawl (prod) | ~4 days | Depends on overlap with Phase 1 |
| Phase 3 crawl (prod) | ~7 days | README fetches are larger |
| **Total Crawl Time** | **~15 days** | With overlap: ~10–12 days |

---

## 20. Open Questions

| # | Question | Status | Resolution |
|---|---|---|---|
| 1 | What percentage threshold for Phase 2 start? | Decided | 25% |
| 2 | Exact HF API `createdAt` behavior for pre-2022 models? | Unknown | Monitor first pages |
| 3 | Need HF Enterprise token for higher limits? | Evaluate after Phase 1 | If 4/s is too slow, upgrade |
| 4 | Should we add `environment` column to rows? | Optional | Can add later if needed |
| 5 | JSONL archive compression level? | TBD | Test gzip vs zstd |

---

*This document is the authoritative reference for the HF Crawl project. Update as decisions evolve.*
