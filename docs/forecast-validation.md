# Forecast validation status

The repository has model, workflow and delivery tests, but no representative
forecast-quality benchmark or executable backtest command. The model tests use
synthetic solar curves and generated output. Passing them establishes behavior
and regression coverage, not measured forecast skill.

The application does not currently persist predictions with their actual later
generation, calculate operational errors, or trigger retraining from those
errors. The default 60/40 ensemble has not been shown here to outperform either
component on held-out field data. Its reported confidence bounds are not a
measured coverage guarantee.

## Inputs needed for a reproducible evaluation

1. A licensed, immutable measured-generation dataset with timestamps, interval
   meaning, units, quality flags, missing/curtailed periods, and system metadata
   (location, timezone, capacity, tilt, azimuth and inverter limits).
2. Weather available at each forecast issue time for the claimed lead time.
   Do not substitute observations or later reanalysis for the original forecast.
3. A chronological train/validation/test split, with no future generation in
   fitting, and fixed source commit, dependencies, model settings and data hashes.
4. Baselines (persistence and physical model), daylight/night handling, and
   separately reported hourly and daily-energy MAE/RMSE/bias. MAPE requires an
   explicit near-zero generation rule; night zeros cannot be silently discarded
   or divided by. Report sample coverage and excluded intervals with every score.

A public starting point is the [PVDAQ dataset](https://data.openei.org/submissions/4568),
which provides measured system performance and site metadata. Individual systems
and periods still need quality screening and a match to the intended use case;
a public dataset alone does not establish representativeness of a home system.
The legacy [PVDAQ v3 API is retired](https://developer.nlr.gov/docs/solar/pvdaq-v3/);
use the linked public data lake and current dataset documentation.

For weather, Open-Meteo distinguishes [historical, previous-run and single-run
archives](https://open-meteo.com/en/docs/historical-forecast-api). Use previous
runs at a fixed lead time or a preserved single run when measuring forecast
skill. The stitched historical series is not equivalent to a forecast that was
available 24 or 48 hours earlier.

These inputs have not been assembled into a benchmark in this repository. No
quality score is reported until the dataset, split, evaluation code and results
can be reviewed together. This evaluation must run without MQTT publication or
hardware control; do not use the ordinary operational CLI as a backtest driver.
