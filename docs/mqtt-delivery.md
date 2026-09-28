# Controller delivery v1

Set `MQTT_BROKER` to the GX broker reachable from the container, not its own
localhost; set `SITE_ID` to the GX `PORTAL_ID`. MQTT_PORT defaults to 1883.
Optional MQTT_USERNAME/MQTT_PASSWORD are passed to the broker. The transport
must be on the site's trusted network (or a protected tunnel).

Forecast summaries use QoS1 and retain on `solar_forecast/<SITE_ID>/forecast_json`.
Missing calendar days remain absent, not zero. PUBACK confirms broker receipt;
controller state must be inspected separately to confirm ingestion.

Pre-charge uses a non-retained QoS1 request and subscribes to a request-specific
ack topic before sending. The controller's status is recorded separately from
broker receipt. Each attempt waits at most 8 seconds; one retry uses the same
payload. Failure is reported as delivery_failed, never as accepted.

The v1 request adds request_id, version, issued_at/expires_at (300 seconds).
The SHA256 ID is based on site and panel-local date, so hourly recalculation and
process restarts use the same ID that the controller durably deduplicates.
Both ends must be updated together. Controller contract is documented in
victron-venus/inverter-control `docs/solar-delivery.md`.

Accepted means the controller queued its existing one-cycle charging intent;
it does not assert sustained charging or measured energy. The producer and
controller retain their expensive-window gates.

The `solar_forecast/<site>` namespace is deliberately outside Venus `N/<portal>`.
The [Venus broker plugin](https://github.com/victronenergy/dbus-flashmq/blob/master/src/flashmq-dbus-plugin.cpp)
reserves `N/<portal>` for its own notifications and denies external publishers.
A MQTT 3.1.1 PUBACK alone does not prove subscriber delivery on that namespace.
Upgrade both producer and controller before using the new topic pair.
