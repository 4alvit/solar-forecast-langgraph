FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016

COPY --from=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 /uv /usr/local/bin/uv

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
