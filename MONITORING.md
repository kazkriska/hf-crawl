# HF Crawl — Monitoring & Observability Guide

Push-based metrics and logs to your existing monitoring LXC at `192.168.1.11`.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  HF Crawl Container                                                          │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐              │
│  │  Crawler     │  │  Metrics     │  │  Log Shipper         │              │
│  │  (3 phases)  │  │  (push loop) │  │  (async queue)       │              │
│  └──────────────┘  └──────┬───────┘  └──────────┬───────────┘              │
│                           │                      │                          │
└───────────────────────────┼──────────────────────┼──────────────────────────┘
                            │                      │
                            │ HTTP push            │ HTTP push
                            │                      │
                            ▼                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Monitoring LXC (192.168.1.11)                                               │
│                                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Pushgateway │  │  Prometheus  │  │   Grafana    │  │    Loki      │  │
│  │  port 9091   │  │  port 9090   │  │  port 3000   │  │  port 3100   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## How It Works

HF Crawl uses **push-based** telemetry — no exporters or sidecars needed.

- **Metrics**: Every 30 seconds, metrics are pushed to Pushgateway (`192.168.1.11:9091`). Prometheus scrapes Pushgateway.
- **Logs**: Structured JSON logs are pushed directly to Loki (`192.168.1.11:3100`) via async queue.
- **Grafana**: Reads from Prometheus (metrics) and Loki (logs).

---

## Quick Verification

```bash
# Check metrics are being pushed
curl http://192.168.1.11:9091/metrics | grep hf_crawl

# Check Prometheus is scraping Pushgateway
curl http://192.168.1.11:9090/targets

# Check Loki is receiving logs
curl http://192.168.1.11:3100/loki/api/v1/label/job/values

# Query in Grafana Explore (LogQL)
{job="hf-crawl"}
{job="hf-crawl", level="error"}
{job="hf-crawl", phase="list"} | json
```

---

## Prometheus Integration

Add to your `prometheus.yml` on the monitoring LXC:

```yaml
scrape_configs:
  - job_name: "pushgateway"
    scrape_interval: 15s
    honor_labels: true
    static_configs:
      - targets: ["localhost:9091"]
```

The `honor_labels: true` ensures job/instance labels from Pushgateway are preserved.

---

## Grafana Integration

### 1. Add Prometheus Data Source (if not already)

1. Go to **Configuration → Data Sources → Add data source**
2. Select **Prometheus**
3. URL: `http://localhost:9090`
4. Click **Save & Test**

### 2. Add Loki Data Source

1. Go to **Configuration → Data Sources → Add data source**
2. Select **Loki**
3. URL: `http://localhost:3100`
4. Click **Save & Test**

### 3. Import Dashboard

1. Go to **Dashboards → Import**
2. Upload `grafana/dashboard.json`
3. Select the Prometheus data source
4. Click **Import**

---

## Metrics Exposed

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

---

## Alert Rules

Copy `hf_crawl_alerts.yml` to your Prometheus rules directory on the monitoring LXC.

| Alert | Condition | Severity |
|-------|-----------|----------|
| `HighRateLimitHits` | `rate(hf_crawl_rate_limit_hits_total[5m]) > 5` | warning |
| `LowDiskSpace` | `hf_crawl_disk_free_bytes < 10GB` | critical |
| `PhaseStuck` | `delta(hf_crawl_phase_progress_pct[30m]) == 0` | warning |
| `HighErrorRate` | `rate(hf_crawl_models_fetched_total{status="error"}[5m]) > 0.1` | warning |
| `CrawlDown` | `up{job="hf-crawl"} == 0` | critical |

---

## Configuration

Monitoring endpoints are configured in `config/config.dev.yaml`:

```yaml
monitoring:
  enabled: true
  pushgateway_host: "192.168.1.11"
  pushgateway_port: 9091
  loki_host: "192.168.1.11"
  loki_port: 3100
  job_name: "hf-crawl"
  instance_name: "dev"
  push_interval_seconds: 30
```

Override via environment variables in Docker:

```bash
docker run -d \
    -e MONITORING_PUSHGATEWAY_HOST=192.168.1.11 \
    -e MONITORING_LOKI_HOST=192.168.1.11 \
    -e MONITORING_INSTANCE_NAME=my-crawler \
    -p 8501:8501 \
    -v hf-crawl-data:/app/data \
    hf-crawl crawl
```

---

## Dashboard Panels

| Panel | Type | Metric |
|-------|------|--------|
| Phase 1/2/3 Progress | Gauge | `hf_crawl_phase_progress_pct` |
| Phase Status | Stat | `hf_crawl_phase_status` |
| Throughput | Time Series | `hf_crawl_throughput_models_per_second` |
| Total Fetched | Counter | `increase(hf_crawl_models_fetched_total[5m])` |
| Request Rate | Time Series | `rate(hf_crawl_requests_total[5m])` |
| Rate Limit Remaining | Gauge | `hf_crawl_rate_limit_remaining` |
| Request Latency | Heatmap | `rate(hf_crawl_request_duration_seconds_bucket[5m])` |
| DB Size | Time Series | `hf_crawl_db_size_bytes` |
| Disk Space | Gauge | `hf_crawl_disk_free_bytes` |
| Active Workers | Time Series | `hf_crawl_active_workers` |
| Error Rate | Time Series | `rate(hf_crawl_rate_limit_hits_total[5m])` |

---

## Troubleshooting

### No metrics in Prometheus
```bash
# Check Pushgateway directly
curl http://192.168.1.11:9091/metrics | grep hf_crawl

# Check Prometheus targets
curl http://192.168.1.11:9090/targets
```

### Logs not appearing in Loki
```bash
# Test Loki manually
TIMESTAMP=$(date +%s%N)
curl -s -X POST http://192.168.1.11:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d "{\"streams\":[{\"stream\":{\"job\":\"test\"},\"values\":[[\"${TIMESTAMP}\",\"test log\"]]}]}"

# Check Loki labels
curl http://192.168.1.11:3100/loki/api/v1/label/job/values
```

### Grafana shows "No data"
- Verify data sources are selected in dashboard settings
- Check time range (default: last 1 hour)
- Verify metrics exist: `http://192.168.1.11:9090/graph?g0.expr=hf_crawl_phase_progress_pct`
