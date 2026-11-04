"""Causal records, fair comparison populations and offline CLI behavior."""

import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from solar_forecast.evaluation import (
    ForecastLedger,
    evaluate,
    iso,
    normalize_actual,
    normalize_forecast,
    normalize_plan,
    record_operational_forecasts,
)
from solar_forecast.evaluation_cli import main
from solar_forecast.evaluation_demo import create_demo

NOW = datetime(2026, 11, 4, tzinfo=UTC)


def forecast(variant="a", *, provenance="archive", points=None):
    return {
        "schema_version": 1,
        "site_id": "test",
        "panel_id": "all",
        "unit": "Wh",
        "interval_seconds": 3600,
        "variant": variant,
        "issued_at": "2026-10-02T23:00:00Z",
        "inputs_available_at": "2026-10-02T22:00:00Z",
        "training_end": "2026-10-01T00:00:00Z",
        "source_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "input_sha256": "c" * 64,
        "provenance": provenance,
        "source": "unit fixture",
        "points": points or [{"target_start": "2026-10-03T00:00:00Z", "energy_wh": 100}],
    }


def actual(*, target="2026-10-03T00:00:00Z", value=80, quality="valid", daylight="day"):
    return {
        "schema_version": 1,
        "site_id": "test",
        "panel_id": "all",
        "unit": "Wh",
        "interval_seconds": 3600,
        "target_start": target,
        "available_at": iso(datetime.fromisoformat(target) + timedelta(hours=1)),
        "energy_wh": value,
        "quality": quality,
        "daylight": daylight,
        "source": "unit fixture",
    }


def plan(*, variants=None):
    return {
        "schema_version": 1,
        "site_id": "test",
        "panel_id": "all",
        "timezone": "UTC",
        "train_end": "2026-10-01T00:00:00Z",
        "validation_end": "2026-10-03T00:00:00Z",
        "test_end": "2026-10-04T00:00:00Z",
        "min_lead_hours": 1,
        "max_lead_hours": 24,
        "variants": variants or ["a", "b"],
    }


@pytest.fixture
def ledger(tmp_path):
    with ForecastLedger(tmp_path / "evidence.sqlite") as value:
        yield value


@pytest.mark.parametrize(
    "key,value",
    [
        ("issued_at", "2026-10-02T23:00:00"),
        ("inputs_available_at", "2026-10-02T23:01:00Z"),
        ("training_end", "2026-10-03T00:00:00Z"),
        ("source_sha256", "+" + "a" * 63),
        ("interval_seconds", 900),
        ("unit", "kWh"),
        ("variant", "persistence"),
    ],
)
def test_rejects_invalid_provenance_or_units(key, value):
    row = forecast()
    row[key] = value
    with pytest.raises((TypeError, ValueError)):
        normalize_forecast(row, NOW)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "80"])
def test_energy_requires_finite_nonnegative_number(value):
    row = forecast()
    row["points"][0]["energy_wh"] = value
    with pytest.raises((TypeError, ValueError)):
        normalize_forecast(row, NOW)


def test_hourly_unique_future_targets_required():
    row = forecast()
    row["points"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        normalize_forecast(row, NOW)
    row["points"] = [{"target_start": "2026-10-03T00:30:00Z", "energy_wh": 100}]
    with pytest.raises(ValueError, match="aligned"):
        normalize_forecast(row, NOW)
    row["points"][0]["target_start"] = row["issued_at"]
    with pytest.raises(ValueError, match="strictly later"):
        normalize_forecast(row, NOW)


def test_live_records_cannot_be_backdated():
    with pytest.raises(ValueError, match="before target_start"):
        normalize_forecast(forecast(provenance="live"), NOW)
    # Explicit archive provenance permits import, but never implies prospective verification.
    assert normalize_forecast(forecast(), NOW)["provenance"] == "archive"


def test_actual_cannot_exist_before_interval_end():
    row = actual()
    row["available_at"] = row["target_start"]
    with pytest.raises(ValueError, match="interval end"):
        normalize_actual(row, NOW)
    row = actual(value=None, quality="missing")
    assert normalize_actual(row, NOW)["energy_wh"] is None
    with pytest.raises(ValueError, match="null"):
        normalize_actual(actual(quality="missing"), NOW)


def test_idempotency_timezone_normalization_and_conflict_rollback(ledger):
    original = forecast()
    assert ledger.append("forecasts", [original], now=NOW) == {"inserted": 1, "duplicates": 0}
    same = deepcopy(original)
    same["points"][0]["target_start"] = "2026-10-02T17:00:00-07:00"
    assert ledger.append("forecasts", [same], now=NOW)["duplicates"] == 1
    conflict = deepcopy(original)
    conflict["points"][0]["energy_wh"] = 1
    with pytest.raises(ValueError, match="conflicting"):
        ledger.append("forecasts", [forecast("b"), conflict], now=NOW)
    assert len(ledger.snapshot(NOW)[0]) == 1  # b also rolled back


def test_actual_conflict_is_not_a_revision(ledger):
    ledger.append("actuals", [actual()], now=NOW)
    with pytest.raises(ValueError, match="conflicting"):
        ledger.append("actuals", [actual(value=81)], now=NOW)
    assert ledger.snapshot(NOW)[1][0]["energy_wh"] == 80


def test_live_retry_is_idempotent_after_the_target_hour(ledger):
    row = forecast(provenance="live")
    issued = datetime(2026, 10, 2, 23, tzinfo=UTC)
    assert ledger.append("forecasts", [row], now=issued)["inserted"] == 1
    assert ledger.append("forecasts", [row], now=NOW)["duplicates"] == 1
    with pytest.raises(ValueError, match="before target_start"):
        ledger.append("forecasts", [forecast("b", provenance="live")], now=NOW)


def test_sql_guard_and_checksum(ledger):
    ledger.append("actuals", [actual()], now=NOW)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.db.execute("DELETE FROM actuals")
    ledger.db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.db.execute("UPDATE actuals SET sha256='invalid'")
    ledger.db.rollback()
    ledger.db.execute("DROP TRIGGER actuals_no_update")
    ledger.db.execute("UPDATE actuals SET sha256='invalid'")
    ledger.db.commit()
    with pytest.raises(ValueError, match="checksum"):
        ledger.snapshot(NOW)


@pytest.mark.parametrize("user_version", [0, 1, 12])
@pytest.mark.parametrize(
    "definition",
    [
        "CREATE TABLE important (value TEXT)",
        "CREATE VIEW important_view AS SELECT 42 AS answer",
        "CREATE VIEW sqliteXimportant_view AS SELECT 42 AS answer",
    ],
)
@pytest.mark.parametrize("readonly", [False, True])
def test_preserve_foreign_database_and_missing_readonly_path(
    tmp_path, user_version, definition, readonly
):
    path = tmp_path / "foreign.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute(definition)
        db.execute(f"PRAGMA user_version = {user_version}")
        db.commit()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="foreign"):
        ForecastLedger(path, readonly=readonly)
    assert path.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        ForecastLedger(tmp_path / "absent.sqlite", readonly=True)
    assert not (tmp_path / "absent.sqlite").exists()


def test_initialize_existing_empty_database(tmp_path):
    path = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("VACUUM")
    with ForecastLedger(path) as store:
        assert store.append("actuals", [actual()], now=NOW)["inserted"] == 1
    with ForecastLedger(path, readonly=True) as store:
        assert len(store.snapshot(NOW)[1]) == 1


@pytest.mark.parametrize("readonly", [False, True])
def test_reject_foreign_objects_added_to_ledger(tmp_path, readonly):
    path = tmp_path / "ledger.sqlite"
    with ForecastLedger(path) as store:
        store.db.execute("CREATE VIEW important_view AS SELECT 42 AS answer")
        store.db.commit()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="foreign"):
        ForecastLedger(path, readonly=readonly)
    assert path.read_bytes() == before


def test_missing_append_only_guards_are_rejected(tmp_path):
    path = tmp_path / "ledger.sqlite"
    with ForecastLedger(path) as store:
        store.db.execute("DROP TRIGGER actuals_no_update")
        store.db.commit()
    with pytest.raises(ValueError, match="guards"):
        ForecastLedger(path)


def test_snapshot_as_of_records_insertion_time(ledger):
    ledger.append("forecasts", [forecast()], now=NOW)
    assert ledger.snapshot(NOW - timedelta(seconds=1))[0] == []


def test_metrics_use_common_population_and_keep_zero_night(ledger):
    points_a = [
        {"target_start": "2026-10-03T00:00:00Z", "energy_wh": 100},
        {"target_start": "2026-10-03T01:00:00Z", "energy_wh": 10},
        {"target_start": "2026-10-03T02:00:00Z", "energy_wh": 900},
    ]
    points_b = [
        {"target_start": "2026-10-03T00:00:00Z", "energy_wh": 60},
        {"target_start": "2026-10-03T01:00:00Z", "energy_wh": 0},
    ]
    ledger.append(
        "forecasts", [forecast("a", points=points_a), forecast("b", points=points_b)], now=NOW
    )
    ledger.append(
        "actuals",
        [actual(), actual(target=points_a[1]["target_start"], value=0, daylight="night")],
        now=NOW,
    )
    result = evaluate(ledger, plan(), as_of=NOW, allow_retrospective=True)
    assert result["coverage"]["union_forecast_rows"] == 3
    assert result["coverage"]["matched_rows"] == 2
    assert result["coverage"]["excluded_rows"] == {"variant_missing": 1}
    assert result["metrics"]["a"]["hourly"]["mae_wh"] == 15
    assert result["metrics"]["a"]["hourly"]["rmse_wh"] == pytest.approx((250) ** 0.5)
    assert result["metrics"]["b"]["hourly"]["bias_wh"] == -10
    assert result["metrics"]["a"]["by_daylight"]["night"]["count"] == 1
    assert result["coverage"]["complete_issue_days"] == 0
    assert len(result["forecast_manifests"]) == 2
    assert result == evaluate(ledger, plan(), as_of=NOW, allow_retrospective=True)


def test_retrospective_is_never_implicitly_treated_as_live(ledger):
    ledger.append("forecasts", [forecast("a"), forecast("b")], now=NOW)
    ledger.append("actuals", [actual()], now=NOW)
    result = evaluate(ledger, plan(), as_of=NOW)
    assert result["status"] == "insufficient_data"
    assert result["forecast_exclusions"] == {"archive": 2}
    assert result["metrics"]["a"]["hourly"]["mae_wh"] is None


@pytest.mark.parametrize("quality", ["curtailed", "missing"])
def test_bad_actuals_excluded_identically(ledger, quality):
    ledger.append("forecasts", [forecast("a"), forecast("b")], now=NOW)
    ledger.append(
        "actuals", [actual(quality=quality, value=None if quality == "missing" else 10)], now=NOW
    )
    result = evaluate(ledger, plan(), as_of=NOW, allow_retrospective=True)
    assert result["coverage"]["excluded_rows"] == {quality: 1}
    assert (
        result["metrics"]["a"]["hourly"]["count"] == result["metrics"]["b"]["hourly"]["count"] == 0
    )


def test_frozen_training_boundary_and_explicit_rolling_mode(ledger):
    rows = [forecast("a"), forecast("b")]
    for row in rows:
        row["training_end"] = "2026-10-02T00:00:00Z"
    ledger.append("forecasts", rows, now=NOW)
    ledger.append("actuals", [actual()], now=NOW)
    with pytest.raises(ValueError, match="fixed training"):
        evaluate(ledger, plan(), as_of=NOW, allow_retrospective=True)
    rolling = {**plan(), "training_policy": "rolling_origin"}
    assert (
        evaluate(ledger, rolling, as_of=NOW, allow_retrospective=True)["coverage"]["matched_rows"]
        == 1
    )
    with pytest.raises(ValueError, match="require train_end"):
        normalize_plan({**plan(), "train_end": "2026-10-04T00:00:00Z"})


def test_persistence_never_uses_future_or_late_arriving_input(ledger):
    ledger.append("forecasts", [forecast()], now=NOW)
    previous = actual(target="2026-10-02T00:00:00Z", value=500)
    previous["available_at"] = "2026-10-02T23:30:00Z"  # after issue
    older = actual(target="2026-10-01T00:00:00Z", value=75)
    ledger.append("actuals", [actual(), previous, older], now=NOW)
    result = evaluate(
        ledger, plan(variants=["a", "persistence"]), as_of=NOW, allow_retrospective=True
    )
    assert result["metrics"]["persistence"]["hourly"]["bias_wh"] == -5


def test_live_persistence_requires_prior_local_record(ledger):
    issue = datetime(2026, 10, 2, 23, tzinfo=UTC)
    ledger.append("forecasts", [forecast(provenance="live")], now=issue)
    # The source claims earlier availability, but it only entered this store after the forecast.
    ledger.append("actuals", [actual(), actual(target="2026-10-02T00:00:00Z", value=75)], now=NOW)
    result = evaluate(ledger, plan(variants=["a", "persistence"]), as_of=NOW)
    assert result["coverage"]["excluded_rows"] == {"variant_missing": 1}


@pytest.mark.parametrize(
    "start,hours", [("2026-03-08T08:00:00+00:00", 23), ("2026-11-01T07:00:00+00:00", 25)]
)
def test_daily_metrics_respect_local_dst(ledger, start, hours):
    beginning = datetime.fromisoformat(start)
    rows = []
    points = []
    for hour in range(hours):
        target = iso(beginning + timedelta(hours=hour))
        points.append({"target_start": target, "energy_wh": 10})
        rows.append(actual(target=target, value=8))
    forecasts = [forecast("a", points=points), forecast("b", points=points)]
    for row in forecasts:
        row["issued_at"] = iso(beginning - timedelta(hours=1))
        row["inputs_available_at"] = row["issued_at"]
        row["training_end"] = "2026-01-01T00:00:00Z"
    ledger.append("forecasts", forecasts, now=NOW)
    ledger.append("actuals", rows, now=NOW)
    settings = {
        **plan(),
        "timezone": "America/Los_Angeles",
        "train_end": "2026-01-01T00:00:00Z",
        "validation_end": iso(beginning),
        "test_end": iso(beginning + timedelta(hours=hours)),
        "max_lead_hours": 25,
    }
    result = evaluate(ledger, settings, as_of=NOW, allow_retrospective=True)
    assert result["coverage"]["complete_issue_days"] == 1
    assert result["metrics"]["a"]["daily"]["mae_wh"] == hours * 2


@pytest.mark.parametrize("actual_value", [1e308, 0])
def test_large_daily_values_are_finite_or_explicitly_rejected(ledger, tmp_path, actual_value):
    start = datetime(2026, 10, 3, tzinfo=UTC)
    points = [
        {"target_start": iso(start + timedelta(hours=hour)), "energy_wh": 1e308}
        for hour in range(24)
    ]
    ledger.append(
        "forecasts", [forecast("a", points=points), forecast("b", points=points)], now=NOW
    )
    ledger.append(
        "actuals", [actual(target=p["target_start"], value=actual_value) for p in points], now=NOW
    )
    if actual_value:
        result = evaluate(ledger, plan(), as_of=NOW, allow_retrospective=True)
        assert result["metrics"]["a"]["daily"] == {
            "count": 1,
            "mae_wh": 0,
            "rmse_wh": 0,
            "bias_wh": 0,
        }
        json.dumps(result, allow_nan=False)
    else:
        with pytest.raises(ValueError, match="finite numeric range"):
            evaluate(ledger, plan(), as_of=NOW, allow_retrospective=True)
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan()))
        output = tmp_path / "report.json"
        assert (
            main(
                [
                    "evaluate",
                    "--ledger",
                    str(ledger.path),
                    "--plan",
                    str(plan_path),
                    "--as-of",
                    iso(NOW),
                    "--allow-retrospective",
                    "--output",
                    str(output),
                ]
            )
            == 2
        )
        assert not output.exists()


def test_operational_record_filters_current_hours_and_records_both_variants(tmp_path):
    issue = datetime(2026, 10, 2, 23, 30, tzinfo=UTC)
    data = {
        "site_id": "test",
        "panel_id": None,
        "points": [
            {"timestamp": "2026-10-02T23:00:00Z", "energy_wh": 1},
            {"timestamp": "2026-10-03T00:00:00Z", "energy_wh": 10},
        ],
    }
    result = record_operational_forecasts(
        tmp_path / "live.sqlite",
        base=data,
        final=data,
        configuration={"site": "test"},
        inputs={},
        now=issue,
    )
    assert result["inserted"] == 2
    assert result["skipped_current_or_past_hours"] == {"base": 1, "final": 1}
    with ForecastLedger(tmp_path / "live.sqlite", readonly=True) as store:
        rows = store.snapshot(NOW)[0]
    assert {row["variant"] for row in rows} == {"base", "final"}
    assert all(len(row["points"]) == 1 and row["provenance"] == "live" for row in rows)


def test_demo_and_cli_replay_refuse_overwrite(tmp_path, capsys):
    directory = tmp_path / "demo"
    report = create_demo(directory, now=NOW)
    assert report["coverage"]["matched_rows"] == 48
    assert report["coverage"]["complete_issue_days"] == 2
    assert (
        report["metrics"]["candidate"]["hourly"]["mae_wh"]
        < report["metrics"]["baseline"]["hourly"]["mae_wh"]
    )
    with pytest.raises(FileExistsError):
        create_demo(directory, now=NOW)
    args = [
        "evaluate",
        "--ledger",
        str(directory / "ledger.sqlite"),
        "--plan",
        str(directory / "plan.json"),
        "--as-of",
        iso(NOW),
        "--allow-retrospective",
        "--output",
        str(directory / "replay.json"),
    ]
    assert main(args) == 0
    replay = json.loads((directory / "replay.json").read_text())
    assert replay["metrics"] == report["metrics"]
    assert main(args) == 2
    assert "File exists" in capsys.readouterr().err


def test_cli_invalid_input_does_not_partially_import(tmp_path, capsys):
    path = tmp_path / "actuals.jsonl"
    path.write_text(json.dumps(actual()) + "\n" + json.dumps(actual(value=-1)))
    destination = tmp_path / "ledger.sqlite"
    assert main(["import-actuals", "--ledger", str(destination), "--input", str(path)]) == 2
    assert "nonnegative" in capsys.readouterr().err
    with ForecastLedger(destination, readonly=True) as store:
        assert store.snapshot(NOW)[1] == []


def test_evaluation_never_imports_runtime_or_uses_network(tmp_path):
    script = """
import importlib.abc, socket, sys
def forbidden(*args, **kwargs):
    raise AssertionError('network forbidden')
socket.socket.connect = forbidden
socket.create_connection = forbidden
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'paho','httpx','langgraph','langchain_openai','numpy','pandas','sklearn','pydantic'}:
            raise AssertionError('runtime import forbidden: ' + fullname)
sys.meta_path.insert(0, Guard())
from solar_forecast.evaluation_cli import main
raise SystemExit(main(['demo','--directory',sys.argv[1]]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "offline")],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_history", [False, True])
async def test_workflow_opt_in_records_without_changing_final_forecast(
    tmp_path, monkeypatch, duplicate_history
):
    from solar_forecast.config import DEFAULT_SITE
    from solar_forecast.history import GenerationRecord, HistoricalData
    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast
    from solar_forecast.workflow import WorkflowState, finalize_forecast_node

    target = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    prediction = GenerationForecast(
        site_id="test",
        panel_id=None,
        forecast_horizon_hours=1,
        method=ForecastMethod.ENSEMBLE,
        points=[
            ForecastPoint(
                timestamp=target,
                energy_wh=10,
                power_w=10,
                confidence_lower=8,
                confidence_upper=12,
                method=ForecastMethod.ENSEMBLE,
            )
        ],
    )
    state = WorkflowState(site_config=DEFAULT_SITE, base_forecast=prediction)
    historical_time = target - timedelta(days=1)
    if duplicate_history:
        state.historical_df = HistoricalData(
            site_id="test",
            panel_id=None,
            start_date=historical_time,
            end_date=historical_time,
            records=[
                GenerationRecord(
                    timestamp=historical_time, site_id="test", panel_id=panel, energy_wh=energy
                )
                for panel, energy in (("east", 10), ("west", 20))
            ],
        ).to_dataframe()
        assert state.historical_df.index.has_duplicates

    observed_inputs = {}

    def record_with_observed_inputs(*args, **kwargs):
        observed_inputs.update(kwargs["inputs"])
        return record_operational_forecasts(*args, **kwargs)

    monkeypatch.setattr(
        "solar_forecast.evaluation.record_operational_forecasts", record_with_observed_inputs
    )
    await finalize_forecast_node(state)
    assert not list(tmp_path.iterdir())
    state.evaluation_ledger = str(tmp_path / "ledger.sqlite")
    await finalize_forecast_node(state)
    assert state.final_forecast is prediction
    assert "record_evaluation" in state.completed_steps
    with ForecastLedger(state.evaluation_ledger, readonly=True) as store:
        assert len(store.snapshot(datetime.now(UTC))[0]) == 2
    if duplicate_history:
        history = json.loads(observed_inputs["history"])
        assert history["index"] == [historical_time.isoformat().replace("+00:00", ".000Z")] * 2
        panel_column = history["columns"].index("panel_id")
        energy_column = history["columns"].index("energy_wh")
        assert [(row[panel_column], row[energy_column]) for row in history["data"]] == [
            ("east", 10),
            ("west", 20),
        ]
    else:
        assert observed_inputs["history"] is None

    def disk_failure(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("solar_forecast.evaluation.record_operational_forecasts", disk_failure)
    await finalize_forecast_node(state)
    assert state.final_forecast is prediction
    assert not state.errors
    assert any("disk unavailable" in warning for warning in state.warnings)
