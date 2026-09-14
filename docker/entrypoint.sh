#!/bin/bash
# HF Crawl — Docker entrypoint
# Supports: crawl, web, shell, test, help

set -e

# --- Resolve config path based on environment ---
if [ "$HF_CRAWL_ENV" = "prod" ]; then
    DEFAULT_CONFIG="/app/config/config.prod.yaml"
else
    DEFAULT_CONFIG="/app/config/config.dev.yaml"
fi

CONFIG="${HF_CRAWL_CONFIG:-$DEFAULT_CONFIG}"

# --- Inject HF_TOKEN into config if provided ---
if [ -n "$HF_TOKEN" ]; then
    sed -i "s|\${HF_TOKEN}|${HF_TOKEN}|g" "$CONFIG" 2>/dev/null || true
fi

# --- Build max-items flag ---
MAX_ITEMS_FLAG=""
if [ -n "$HF_CRAWL_MAX_ITEMS" ]; then
    MAX_ITEMS_FLAG="--max-items $HF_CRAWL_MAX_ITEMS"
fi

# --- Inject monitoring env vars into config ---
# These can be overridden via environment variables
if [ -n "$MONITORING_PUSHGATEWAY_HOST" ]; then
    sed -i "s/pushgateway_host:.*/pushgateway_host: \"$MONITORING_PUSHGATEWAY_HOST\"/" "$CONFIG" 2>/dev/null || true
fi
if [ -n "$MONITORING_PUSHGATEWAY_PORT" ]; then
    sed -i "s/pushgateway_port:.*/pushgateway_port: $MONITORING_PUSHGATEWAY_PORT/" "$CONFIG" 2>/dev/null || true
fi
if [ -n "$MONITORING_LOKI_HOST" ]; then
    sed -i "s/loki_host:.*/loki_host: \"$MONITORING_LOKI_HOST\"/" "$CONFIG" 2>/dev/null || true
fi
if [ -n "$MONITORING_LOKI_PORT" ]; then
    sed -i "s/loki_port:.*/loki_port: $MONITORING_LOKI_PORT/" "$CONFIG" 2>/dev/null || true
fi
if [ -n "$MONITORING_JOB_NAME" ]; then
    sed -i "s/job_name:.*/job_name: \"$MONITORING_JOB_NAME\"/" "$CONFIG" 2>/dev/null || true
fi
if [ -n "$MONITORING_INSTANCE_NAME" ]; then
    sed -i "s/instance_name:.*/instance_name: \"$MONITORING_INSTANCE_NAME\"/" "$CONFIG" 2>/dev/null || true
fi
if [ -n "$MONITORING_PUSH_INTERVAL" ]; then
    sed -i "s/push_interval_seconds:.*/push_interval_seconds: $MONITORING_PUSH_INTERVAL/" "$CONFIG" 2>/dev/null || true
fi

# --- Command routing ---
CMD="${1:-crawl}"
shift || true

case "$CMD" in
    crawl)
        echo "Starting HF Crawl (env=$HF_CRAWL_ENV, config=$CONFIG)..."
        echo "  Metrics → Pushgateway at ${MONITORING_PUSHGATEWAY_HOST:-192.168.1.11}:${MONITORING_PUSHGATEWAY_PORT:-9091}"
        echo "    Logs  → Loki at ${MONITORING_LOKI_HOST:-192.168.1.11}:${MONITORING_LOKI_PORT:-3100}"
        exec python -m src.main --phase all $MAX_ITEMS_FLAG --config "$CONFIG"
        ;;

    list)
        echo "Starting HF Crawl [list phase]..."
        exec python -m src.main --phase list $MAX_ITEMS_FLAG --config "$CONFIG"
        ;;

    info)
        echo "Starting HF Crawl [info phase]..."
        exec python -m src.main --phase info $MAX_ITEMS_FLAG --config "$CONFIG"
        ;;

    card)
        echo "Starting HF Crawl [card phase]..."
        exec python -m src.main --phase card $MAX_ITEMS_FLAG --config "$CONFIG"
        ;;

    web)
        echo "Starting Web UI on port ${HF_CRAWL_WEB_PORT:-8501}..."
        exec streamlit run /app/web/app.py --server.port "${HF_CRAWL_WEB_PORT:-8501}" --server.address 0.0.0.0
        ;;

    test)
        echo "Running tests..."
        exec python -m pytest /app/tests/ -v "$@"
        ;;

    shell)
        echo "Starting interactive shell..."
        exec /bin/bash
        ;;

    version)
        echo "HF Crawl Docker Image"
        echo "  Python: $(python --version)"
        echo "  DuckDB: $(python -c 'import duckdb; print(duckdb.__version__)')"
        echo "  Env: $HF_CRAWL_ENV"
        echo "  Config: $CONFIG"
        ;;

    help|--help|-h)
        cat <<'EOF'
HF Crawl — Docker Container

USAGE:
    hf-crawl <command> [options]

COMMANDS:
    crawl           Run full 3-phase crawl (default)
    list            Run list phase only
    info            Run info phase only
    card            Run card phase only
    web             Start Streamlit web UI
    test            Run test suite
    shell           Start interactive bash shell
    version         Show version info

ENVIRONMENT VARIABLES:
    HF_TOKEN                    Hugging Face API token (injected into requests)
    HF_CRAWL_ENV                dev or prod (default: dev)
    HF_CRAWL_MAX_ITEMS          Max items per phase (for testing)
    HF_CRAWL_WEB_PORT           Web UI port (default: 8501)

    MONITORING_PUSHGATEWAY_HOST Pushgateway host (default: 192.168.1.11)
    MONITORING_PUSHGATEWAY_PORT Pushgateway port (default: 9091)
    MONITORING_LOKI_HOST        Loki host (default: 192.168.1.11)
    MONITORING_LOKI_PORT        Loki port (default: 3100)
    MONITORING_JOB_NAME         Job name label (default: hf-crawl)
    MONITORING_INSTANCE_NAME    Instance name label (default: dev)
    MONITORING_PUSH_INTERVAL    Seconds between pushes (default: 30)

VOLUMES:
    /app/data           DuckDB databases + checkpoints + archives
    /app/logs           Structured JSON logs

PORTS:
    8501                Web UI (Streamlit)
    (Metrics/logs pushed directly to monitoring LXC — no ports needed)

EXAMPLES:
    # Run with custom token, mount data volume
    docker run -d \
        --name hf-crawl \
        -e HF_TOKEN=hf_xxxxx \
        -v hf-crawl-data:/app/data \
        -p 8501:8501 \
        hf-crawl crawl

    # Run 50-item smoke test
    docker run --rm \
        -e HF_CRAWL_MAX_ITEMS=50 \
        -v hf-crawl-data:/app/data \
        hf-crawl crawl

    # Start web UI
    docker run -d \
        --name hf-crawl-web \
        -v hf-crawl-data:/app/data \
        -p 8501:8501 \
        hf-crawl web

    # Interactive shell
    docker run -it --rm \
        -v hf-crawl-data:/app/data \
        hf-crawl shell
EOF
        ;;

    *)
        echo "Unknown command: $CMD"
        echo "Run 'hf-crawl help' for usage."
        exit 1
        ;;
esac
