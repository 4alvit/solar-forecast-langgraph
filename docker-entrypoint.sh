#!/bin/sh
# Hourly forecast loop for container deployment.
set -u

INTERVAL="${FORECAST_INTERVAL_SECONDS:-3600}"
HORIZON="${FORECAST_HORIZON_HOURS:-48}"

ARGS="--horizon ${HORIZON}"
if [ -n "${SITE_CONFIG:-}" ]; then
    ARGS="${ARGS} -c ${SITE_CONFIG}"
fi

echo "[entrypoint] interval=${INTERVAL}s horizon=${HORIZON}h args='${ARGS}'"

while true; do
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] running forecast"
    # shellcheck disable=SC2086
    solar-forecast ${ARGS} \
        || echo "[entrypoint] forecast run failed, retrying next cycle"
    sleep "${INTERVAL}"
done
