# HF Crawl — All-in-one container
# Includes: crawler, web UI (Streamlit)

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


# Copy source code
COPY src/ /app/src/
COPY config/ /app/config/
COPY tests/ /app/tests/
COPY grafana/ /app/grafana/
COPY prometheus.yml /app/prometheus.yml
COPY hf_crawl_alerts.yml /app/hf_crawl_alerts.yml
COPY README.md /app/README.md
COPY ACTION_PLAN.md /app/ACTION_PLAN.md


# Create data and logs directories
RUN mkdir -p /app/data/dev /app/data/prod /app/logs

# Copy entrypoint
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Environment variables with defaults
ENV HF_TOKEN=""
# HF_CRAWL_CONFIG is derived from HF_CRAWL_ENV in entrypoint.sh
# Do not hardcode it here so env-based config selection works
ENV HF_CRAWL_WEB_PORT=8501
ENV HF_CRAWL_ENV=dev
ENV HF_CRAWL_MAX_ITEMS=""

# Expose ports
# 8501 = Web UI (Streamlit)
EXPOSE 8501 8001

# Volume for data persistence
VOLUME ["/app/data", "/app/logs"]

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["crawl"]
