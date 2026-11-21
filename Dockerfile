FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY solar_forecast ./solar_forecast
RUN uv sync --locked --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH"

RUN groupadd --gid 10001 forecast \
    && useradd --uid 10001 --gid forecast --create-home forecast \
    && chown forecast:forecast /app
USER 10001:10001

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Configuration via environment variables:
#   INVERTER_CONTROL_URL       - inverter-control webhook base URL (default http://localhost:8081)
#   MONITORING_URL             - inverter-monitoring generation API (default http://localhost:8080)
#   FORECAST_INTERVAL_SECONDS  - seconds between runs (default 3600)
#   FORECAST_HORIZON_HOURS     - forecast horizon (default 48)
#   SITE_CONFIG                - optional path to site config .py mounted into the container
ENTRYPOINT ["docker-entrypoint.sh"]
