#!/bin/bash
# HF Crawl — Docker entrypoint
# Supports: crawl, list, info, card, shell, test

set -e

# --- Resolve config path based on environment ---
if [ "$HF_CRAWL_ENV" = "prod" ]; then
    DEFAULT_CONFIG="/app/config/config.prod.yaml"
else
    DEFAULT_CONFIG="/app/config/config.dev.yaml"
fi

CONFIG="${HF_CRAWL_CONFIG:-$DEFAULT_CONFIG}"

# --- Logging ---
echo "========================================="
echo "  HF Crawl Docker Container"
echo "========================================="
echo "  Config: $CONFIG"
echo "========================================="

case "${1:-crawl}" in
    crawl)
        echo "Starting HF Crawl [all phases]..."
        exec python -m src.main --phase all --config "$CONFIG"
        ;;

    list)
        echo "Starting HF Crawl [list phase]..."
        exec python -m src.main --phase list --config "$CONFIG"
        ;;

    info)
        echo "Starting HF Crawl [info phase]..."
        exec python -m src.main --phase info --config "$CONFIG"
        ;;

    card)
        echo "Starting HF Crawl [card phase]..."
        exec python -m src.main --phase card --config "$CONFIG"
        ;;

    shell)
        echo "Starting interactive shell..."
        exec /bin/bash
        ;;

    test)
        echo "Running tests..."
        exec python -m pytest tests/ -v
        ;;

    help|--help|-h)
        echo "Usage: docker compose up -d [crawl|list|info|card|shell|test]"
        echo ""
        echo "Commands:"
        echo "  crawl           Run all 3 phases (list → info → card)"
        echo "  list            Run only Phase 1 (model listing)"
        echo "  info            Run only Phase 2 (model info fetch)"
        echo "  card            Run only Phase 3 (model card fetch)"
        echo "  shell           Start interactive bash shell"
        echo "  test            Run test suite"
        exit 0
        ;;

    *)
        echo "Unknown command: $1"
        echo "Usage: docker compose up -d [crawl|list|info|card|shell|test]"
        exit 1
        ;;
esac
