#!/bin/bash
# HF Crawl — Docker convenience wrapper
# Provides easy commands for managing the container and interacting with it.

set -e

IMAGE_NAME="${HF_CRAWL_IMAGE:-hf-crawl}"
CONTAINER_NAME="${HF_CRAWL_CONTAINER:-hf-crawl}"
DATA_DIR="${HF_CRAWL_DATA:-$HOME/.hf-crawl/data}"
LOGS_DIR="${HF_CRAWL_LOGS:-$HOME/.hf-crawl/logs}"
METRICS_PORT="${HF_CRAWL_METRICS_PORT:-8000}"
WEB_PORT="${HF_CRAWL_WEB_PORT:-8501}"

# Ensure dirs exist
mkdir -p "$DATA_DIR" "$LOGS_DIR"

help() {
    cat <<EOF
HF Crawl — Docker CLI Wrapper

USAGE:
    hf-crawl-docker <command>

COMMANDS:
    build           Build the Docker image
    start           Start the crawler container (detached)
    stop            Stop the container
    restart         Restart the container
    logs            View container logs
    shell           Open interactive shell in running container
    crawl           Run full crawl in container
    list            Run list phase
    info            Run info phase
    card            Run card phase
    web             Start web UI (port $WEB_PORT)
    metrics         Check metrics endpoint
    status          Show container status
    cleanup         Stop and remove container + image

ENVIRONMENT:
    HF_CRAWL_IMAGE      Image name (default: hf-crawl)
    HF_CRAWL_CONTAINER  Container name (default: hf-crawl)
    HF_CRAWL_DATA       Data directory (default: ~/.hf-crawl/data)
    HF_CRAWL_LOGS       Logs directory (default: ~/.hf-crawl/logs)
    HF_CRAWL_METRICS_PORT  Metrics port (default: 8000)
    HF_CRAWL_WEB_PORT   Web UI port (default: 8501)

EXAMPLES:
    # Build and start
    hf-crawl-docker build
    HF_TOKEN=hf_xxx hf-crawl-docker start

    # Check status
    hf-crawl-docker status
    hf-crawl-docker metrics

    # Run specific phase
    hf-crawl-docker list

    # Start web UI
    hf-crawl-docker web

    # Interactive shell
    hf-crawl-docker shell

    # Cleanup
    hf-crawl-docker cleanup
EOF
}

build() {
    echo "Building HF Crawl Docker image..."
    docker build -t "$IMAGE_NAME" "$(dirname "$0")/../../.."
    echo "✓ Image built: $IMAGE_NAME"
}

start() {
    echo "Starting HF Crawl container..."
    docker run -d \
        --name "$CONTAINER_NAME" \
        -e HF_TOKEN="${HF_TOKEN:-}" \
        -e HF_CRAWL_ENV="${HF_CRAWL_ENV:-prod}" \
        -e HF_CRAWL_MAX_ITEMS="${HF_CRAWL_MAX_ITEMS:-}" \
        -v "$DATA_DIR:/app/data" \
        -v "$LOGS_DIR:/app/logs" \
        -p "$METRICS_PORT:8000" \
        -p "$WEB_PORT:8501" \
        --restart unless-stopped \
        "$IMAGE_NAME" crawl
    echo "✓ Container started: $CONTAINER_NAME"
    echo "  Metrics: http://localhost:$METRICS_PORT/metrics"
    echo "  Data: $DATA_DIR"
    echo "  Logs: $LOGS_DIR"
}

stop() {
    echo "Stopping container..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    echo "✓ Container stopped"
}

restart() {
    stop
    start
}

logs() {
    docker logs -f "$CONTAINER_NAME" "$@"
}

shell() {
    docker exec -it "$CONTAINER_NAME" /bin/bash
}

crawl() {
    docker exec -it "$CONTAINER_NAME" hf-crawl crawl "$@"
}

list() {
    docker exec -it "$CONTAINER_NAME" hf-crawl list "$@"
}

info() {
    docker exec -it "$CONTAINER_NAME" hf-crawl info "$@"
}

card() {
    docker exec -it "$CONTAINER_NAME" hf-crawl card "$@"
}

web() {
    docker exec -d "$CONTAINER_NAME" hf-crawl web
    echo "✓ Web UI started: http://localhost:$WEB_PORT"
}

metrics() {
    echo "=== Prometheus Metrics ==="
    curl -s "http://localhost:$METRICS_PORT/metrics" | grep "^# HELP hf_crawl" | while read -r line; do
        metric=$(echo "$line" | sed 's/# HELP //')
        echo "  $metric"
    done
    echo ""
    echo "Raw: http://localhost:$METRICS_PORT/metrics"
}

status() {
    echo "=== Container Status ==="
    docker ps --filter "name=$CONTAINER_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null
    echo ""
    echo "=== Data Directory ==="
    du -sh "$DATA_DIR" 2>/dev/null
    ls -la "$DATA_DIR" 2>/dev/null
    echo ""
    echo "=== Recent Logs ==="
    tail -5 "$LOGS_DIR/dev.log" 2>/dev/null || echo "(no logs)"
}

cleanup() {
    echo "Cleaning up..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    docker rmi "$IMAGE_NAME" 2>/dev/null || true
    echo "✓ Cleaned up"
}

# Route commands
CMD="${1:-help}"
shift || true

case "$CMD" in
    build) build "$@" ;;
    start) start "$@" ;;
    stop) stop "$@" ;;
    restart) restart "$@" ;;
    logs) logs "$@" ;;
    shell) shell "$@" ;;
    crawl) crawl "$@" ;;
    list) list "$@" ;;
    info) info "$@" ;;
    card) card "$@" ;;
    web) web "$@" ;;
    metrics) metrics "$@" ;;
    status) status "$@" ;;
    cleanup) cleanup "$@" ;;
    help|--help|-h) help ;;
    *) echo "Unknown command: $CMD"; help; exit 1 ;;
esac
