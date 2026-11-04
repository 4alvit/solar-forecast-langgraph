# Forecast evidence and evaluation

`solar-forecast-evaluate` records hourly forecasts and later observations in an
append-only SQLite ledger, then scores fixed variants on the same chronological
holdout. It uses only Python's standard library. It never imports the operational
workflow, opens a network connection, reads credentials, publishes MQTT or
triggers inverter control. It is also available from a source checkout as
`python -m solar_forecast.evaluation_cli`.

The repository still has **no measured field-quality result**. The runnable demo
below uses constructed values to check the accounting. It does not establish that
the 60/40 ensemble, its confidence bounds, or optional language-model adjustments
improve real forecasts. This evaluator scores supplied forecasts; it does not
train a model or reconstruct missing historical weather inputs.

## Run the complete offline demonstration

Use a new output directory. Existing files are never replaced:

```bash
python -m solar_forecast.evaluation_cli demo --directory /tmp/solar-evaluation-demo
```

This creates `forecasts.jsonl`, `actuals.jsonl`, `plan.json`, `ledger.sqlite` and
`report.json`. The test holdout contains 48 matched hourly forecasts and two
complete UTC days. The variants `baseline` and `candidate` intentionally contain
10% and 5% errors; they are not outputs of the physical/statistical models.
`persistence` is calculated by the evaluator from previously available actuals.
The report labels the forecast provenance as `synthetic`.

Reimporting and replaying is deterministic for the same ledger snapshot and
explicit `as_of`. Use the `as_of` value printed in `report.json`:

```bash
python -m solar_forecast.evaluation_cli import-forecasts \
  --ledger /tmp/solar-evaluation-demo/ledger.sqlite \
  --input /tmp/solar-evaluation-demo/forecasts.jsonl
python -m solar_forecast.evaluation_cli import-actuals \
  --ledger /tmp/solar-evaluation-demo/ledger.sqlite \
  --input /tmp/solar-evaluation-demo/actuals.jsonl
EVALUATION_AS_OF=$(python -c 'import json; print(json.load(open("/tmp/solar-evaluation-demo/report.json"))["as_of"])')
python -m solar_forecast.evaluation_cli evaluate \
  --ledger /tmp/solar-evaluation-demo/ledger.sqlite \
  --plan /tmp/solar-evaluation-demo/plan.json \
  --as-of "$EVALUATION_AS_OF" --allow-retrospective \
  --output /tmp/solar-evaluation-demo/replay.json
```

Exact retries return `duplicates`; changed content at an existing key fails the
whole import transaction. A report destination must not already exist. Exit
codes are `0` for a completed import/evaluation, `2` for invalid input/I/O, and
`3` for an evaluation without matched data. Inspect `coverage` even on exit `0`.

## Record live forecasts before the outcome

Recording is opt-in on the existing operational command:

```bash
solar-forecast --config site_config.local.py --horizon 48 \
  --evaluation-ledger /absolute/path/forecast-evidence.sqlite
```

This is still the **operational command**, with its existing delivery behavior.
Do not run it as a backtest. `run_forecast` and `run_forecast_streaming` accept the
same `evaluation_ledger` option programmatically. Without the option, no ledger
is opened and ordinary behavior is unchanged.

After finalizing the forecast and before delivery, the workflow records `base`
and `final` under one issue time. Only full UTC hours starting strictly after
that recording time are retained. Current/past hours returned by a provider are
not backdated. The record contains hashes of the configuration, input snapshot
and relevant implementation source, not API keys. The training cutoff is the
recording time, a conservative upper bound on inputs used by this live workflow.
Use `training_policy: "rolling_origin"` when evaluating these operational runs.
Writing errors are reported as workflow warnings and never change the ordinary
inverter decision path. A missing ledger record is not evidence of a prediction.

**Actuals require a separate import; this option records predictions only.**
Have the metering/export pipeline produce the hourly actual JSONL contract below,
then append it to the same ledger after the hours have finished:

```bash
solar-forecast-evaluate import-actuals \
  --ledger /absolute/path/forecast-evidence.sqlite \
  --input /absolute/path/hourly-meter-actuals.jsonl
```

The existing `historical_df` is not imported automatically. Its source records
lack per-window sample counts and quality flags, its resampling can represent
empty bins as zero, and the Influx mean-window timestamp needs explicit interval
start/end interpretation. These values cannot establish complete measured hours
without a checked source adapter. The export must preserve coverage, interval
meaning and the time the observation became available; do not copy training
resamples into the ledger and label them measured ground truth.

## Import contract

Import UTF-8 JSONL with one object per line. Unknown fields and malformed records
fail. All timestamps need explicit timezones and are normalized to UTC.
`target_start` must fall on a UTC hour; every value is **Wh over the following
3600 seconds**. Instantaneous W, cumulative meter counters, kWh and intervals of
other lengths must be converted and quality-checked by the source adapter.

A forecast record has this shape (hash placeholders must be actual 64-character
SHA-256 hex strings; this example is schematic):

```json
{
  "schema_version": 1,
  "site_id": "my-site",
  "panel_id": "all",
  "unit": "Wh",
  "interval_seconds": 3600,
  "variant": "physical",
  "issued_at": "2026-10-02T23:30:00Z",
  "inputs_available_at": "2026-10-02T23:20:00Z",
  "training_end": "2026-10-01T00:00:00Z",
  "source_sha256": "<implementation digest>",
  "config_sha256": "<model and site settings digest>",
  "input_sha256": "<immutable input dataset digest>",
  "provenance": "archive",
  "source": "versioned forecast export and input manifest",
  "points": [{"target_start": "2026-10-03T00:00:00Z", "energy_wh": 12.5}]
}
```

Requirements: `training_end <= inputs_available_at <= issued_at <= import time`
and every target is later than issue time. `live` provenance additionally requires
insertion before the target hour begins. `archive` explicitly means retrospectively
imported forecasts whose original provenance must be checked separately.
`synthetic` is reserved for generated examples. Only `live` records are considered
by default; the other two require `--allow-retrospective` and remain labeled in
the report. Historical dates or hashes alone do not prove absence of data leakage.

An actual observation has this shape:

```json
{
  "schema_version": 1,
  "site_id": "my-site",
  "panel_id": "all",
  "unit": "Wh",
  "interval_seconds": 3600,
  "target_start": "2026-10-03T00:00:00Z",
  "available_at": "2026-10-03T01:05:00Z",
  "energy_wh": 10.0,
  "quality": "valid",
  "daylight": "night",
  "source": "meter export revision and quality manifest"
}
```

`available_at` must be at or after the interval end and no later than import time.
`quality` is `valid`, `missing` (requires null energy), or `curtailed`.
`daylight` is `day`, `night`, or `unknown`; zero generation does not infer night.
Energy is finite and nonnegative. Missing rows and explicit missing observations
are counted separately. Curtailment is excluded from all compared variants.

Forecast identity is `(site_id, panel_id, variant, issued_at)`; actual identity is
`(site_id, panel_id, target_start)`. Keep one meter/aggregation definition per
identity. Use a new ledger/dataset revision for corrected historical evidence;
do not silently replace old measurements. SQLite triggers prevent accidental
updates/deletes and payload digests detect corruption. This is not a signed or
tamper-proof archive against someone controlling the database file.

## Freeze the comparison before looking at the test result

A JSON plan fixes the site, variants, lead-time window and temporal boundaries:

```json
{
  "schema_version": 1,
  "site_id": "my-site",
  "panel_id": "all",
  "timezone": "America/Los_Angeles",
  "train_end": "2026-10-01T00:00:00Z",
  "validation_end": "2026-10-03T00:00:00Z",
  "test_end": "2026-10-10T00:00:00Z",
  "min_lead_hours": 0.5,
  "max_lead_hours": 24,
  "variants": ["physical", "ensemble", "persistence"],
  "training_policy": "frozen"
}
```

Validation targets are in `[train_end, validation_end)`; test targets are in
`[validation_end, test_end)`. Select `--phase validation` when developing a variant;
keep test data untouched until the comparison is fixed. In `frozen` mode (default),
records declaring training after `train_end` fail. `rolling_origin` is a separate
prequential evaluation: models may use observations available before each issue
time. It does not claim a frozen-model test. Both modes reject future-input
timestamps when records enter the ledger. External training and archive metadata
remain assertions of their producer.

Comparison identity is `(issued_at, target_start)`. All variants are scored on
the intersection of their predictions and the same valid, available actuals.
Different issue schedules are **not** silently joined as though they were the
same forecast. Missing variants reduce common coverage and are reported; do not
interpret good scores on a small intersection as general model superiority.

The reserved `persistence` variant uses the latest valid measurement for the same
UTC hour, looking back one through seven days, available no later than issue time.
In prospective mode it must also have been inserted in the ledger before issue
time. This baseline never borrows later arrivals or a future day's generation.

## Read the report

- Hourly MAE, RMSE and bias are in Wh; positive bias means overprediction. Zero
  and night values remain in the denominator. Separate daylight buckets expose
  dilution by night zeros. MAPE is intentionally absent.
- Daily metrics sum Wh per local day **from one issue time**, and include only
  complete shared days. DST days can contain 23 or 25 hours. Incomplete days are
  counted, not scaled up. Daily metrics currently require whole-hour local day
  boundaries; fractional-offset timezones fail explicitly.
- `union_forecast_rows`, `available_by_variant`, `matched_rows`, exclusions and
  `matched_fraction` show coverage. Repeated issues for one target are forecast
  cases, not independent meter observations.
- `plan_sha256`, `evidence_sha256`, `as_of` and `forecast_manifests` identify the
  comparison and input snapshot. A snapshot uses a single SQLite read transaction.
- Empty samples produce null metrics and `insufficient_data`, never a zero error.

## Field data still needed

Use licensed measured generation with timestamps, interval definitions, quality
flags, missing/curtailed periods and system metadata (location, timezone,
capacity, tilt, azimuth and inverter limits). Preserve weather forecasts as they
were available at issue time; observations or later reanalysis are not substitutes.
Save source revision, dependencies, settings and dataset hashes with every run.

The [PVDAQ public data lake](https://data.openei.org/submissions/4568) is one starting
point for measured generation; its systems still need representativeness and
quality screening. The [legacy PVDAQ v3 API is retired](https://developer.nlr.gov/docs/solar/pvdaq-v3/).
Open-Meteo distinguishes [historical, previous-run and single-run archives](https://open-meteo.com/en/docs/historical-forecast-api).
Use original runs at the intended lead time when evaluating weather-driven
forecasts. Those datasets have not been assembled into a field benchmark here.
There is no automatic retraining, prompt promotion, deployment or scheduler.
