# HF Crawl — All-in-one container
# Includes: crawler, web UI (Streamlit), Prometheus metrics

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy web UI requirements
COPY hf-crawl-web/requirements.txt /app/web-requirements.txt
RUN pip install --no-cache-dir -r web-requirements.txt

# Copy source code
COPY src/ /app/src/
COPY config/ /app/config/
COPY tests/ /app/tests/
COPY logs/ /app/logs/
COPY grafana/ /app/grafana/
COPY prometheus.yml /app/prometheus.yml
COPY hf_crawl_alerts.yml /app/hf_crawl_alerts.yml
COPY promtail.yml /app/promtail.yml
COPY README.md /app/README.md
COPY ACTION_PLAN.md /app/ACTION_PLAN.md

# Copy web UI (now inside the project)
COPY hf-crawl-web/app.py /app/web/app.py

# Create data and logs directories
RUN mkdir -p /app/data/dev /app/data/prod /app/logs

# Copy entrypoint and CLI wrapper
COPY docker/entrypoint.sh /app/entrypoint.sh
COPY docker/hf-crawl /usr/local/bin/hf-crawl
RUN chmod +x /app/entrypoint.sh /usr/local/bin/hf-crawl

# Environment variables with defaults
ENV HF_TOKEN=""
ENV HF_CRAWL_CONFIG=/app/config/config.dev.yaml
ENV HF_CRAWL_PORT=8000
ENV HF_CRAWL_WEB_PORT=8501
ENV HF_CRAWL_ENV=dev
ENV HF_CRAWL_MAX_ITEMS=""

# Expose ports
# 8000 = Prometheus metrics
# 8501 = Web UI
EXPOSE 8000 8501

# Volume for data persistence
VOLUME ["/app/data", "/app/logs"]

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["--help"]
