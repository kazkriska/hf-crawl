from prometheus_client import Counter, Gauge, Histogram

# Counters
MODELS_FETCHED_TOTAL = Counter(
    'hf_crawl_models_fetched_total',
    'Total models fetched',
    ['phase', 'status'],
)

REQUESTS_TOTAL = Counter(
    'hf_crawl_requests_total',
    'Total HTTP requests',
    ['endpoint', 'status_code'],
)

RATE_LIMIT_HITS_TOTAL = Counter(
    'hf_crawl_rate_limit_hits_total',
    'Total 429 rate limit hits',
    ['endpoint'],
)

# Gauges
PHASE_PROGRESS_PCT = Gauge(
    'hf_crawl_phase_progress_pct',
    'Current phase progress percentage',
    ['phase'],
)

PHASE_STATUS = Gauge(
    'hf_crawl_phase_status',
    'Phase status: 0=pending, 1=running, 2=complete, 3=failed',
    ['phase'],
)

RATE_LIMIT_REMAINING = Gauge(
    'hf_crawl_rate_limit_remaining',
    'Remaining requests in current window',
    ['bucket'],
)

DB_SIZE_BYTES = Gauge(
    'hf_crawl_db_size_bytes',
    'Database file size in bytes',
)

DISK_FREE_BYTES = Gauge(
    'hf_crawl_disk_free_bytes',
    'Free disk space in bytes',
)

ACTIVE_WORKERS = Gauge(
    'hf_crawl_active_workers',
    'Number of active async workers',
    ['phase'],
)

THROUGHPUT_MODELS_PER_SECOND = Gauge(
    'hf_crawl_throughput_models_per_second',
    'Current crawl speed in models per second',
    ['phase'],
)

# Histograms
REQUEST_DURATION_SECONDS = Histogram(
    'hf_crawl_request_duration_seconds',
    'HTTP request latency',
    ['endpoint', 'status_code'],
    buckets=(.005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0),
)

BATCH_COMMIT_DURATION_SECONDS = Histogram(
    'hf_crawl_batch_commit_duration_seconds',
    'DB commit time',
    ['phase'],
    buckets=(.001, .005, .01, .025, .05, .1, .25, .5, 1.0, 2.5, 5.0),
)
