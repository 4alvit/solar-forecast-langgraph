FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY solar_forecast ./solar_forecast
RUN pip install --no-cache-dir .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Configuration via environment variables:
#   INVERTER_CONTROL_URL       - inverter-control webhook base URL (default http://localhost:8081)
#   MONITORING_URL             - inverter-monitoring generation API (default http://localhost:8080)
#   FORECAST_INTERVAL_SECONDS  - seconds between runs (default 3600)
#   FORECAST_HORIZON_HOURS     - forecast horizon (default 48)
#   SITE_CONFIG                - optional path to site config .py mounted into the container
ENTRYPOINT ["docker-entrypoint.sh"]
