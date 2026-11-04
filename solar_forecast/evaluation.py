"""Offline, append-only forecast evidence and chronological comparisons.

This module deliberately depends only on the standard library. It neither runs
the operational forecast workflow nor reads site configuration or credentials.
Energy values are Wh for the UTC hour starting at ``target_start``.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1
APPLICATION_ID = 0x53464556  # SFEV; user_version alone is not a database identity.
HOUR = timedelta(hours=1)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value: str, name: str, *, hourly: bool = False) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be an ISO-8601 string with timezone")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    result = result.astimezone(UTC)
    if hourly and (result.minute or result.second or result.microsecond):
        raise ValueError(f"{name} must be aligned to a UTC hour")
    return result


def iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must include a timezone")
    return value.astimezone(UTC).isoformat()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{name} must be nonempty text of at most 512 characters")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite nonnegative number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} is too large") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return result


def _hash(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    if any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return value.lower()


def _keys(obj: dict, required: set[str], optional: set[str] | None = None) -> None:
    if not isinstance(obj, dict):
        raise TypeError("record must be an object")
    missing = required - obj.keys()
    unknown = obj.keys() - required - (optional or set())
    if missing or unknown:
        raise ValueError(
            f"invalid record fields: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _common(record: dict) -> dict:
    if record["schema_version"] != SCHEMA_VERSION or isinstance(record["schema_version"], bool):
        raise ValueError("unsupported schema_version")
    if record["unit"] != "Wh" or record["interval_seconds"] != 3600:
        raise ValueError("only Wh energy over 3600-second intervals is supported")
    return {
        "schema_version": SCHEMA_VERSION,
        "site_id": _text(record["site_id"], "site_id"),
        "panel_id": _text(record["panel_id"], "panel_id"),
        "unit": "Wh",
        "interval_seconds": 3600,
    }


COMMON = {"schema_version", "site_id", "panel_id", "unit", "interval_seconds"}


def normalize_forecast(record: dict, now: datetime, *, check_recording_time: bool = True) -> dict:
    _keys(
        record,
        COMMON
        | {
            "variant",
            "issued_at",
            "inputs_available_at",
            "training_end",
            "source_sha256",
            "config_sha256",
            "input_sha256",
            "provenance",
            "source",
            "points",
        },
    )
    result = _common(record)
    now = timestamp(iso(now), "clock")
    issued = timestamp(record["issued_at"], "issued_at")
    inputs = timestamp(record["inputs_available_at"], "inputs_available_at")
    training = timestamp(record["training_end"], "training_end")
    if not training <= inputs <= issued <= now:
        raise ValueError("require training_end <= inputs_available_at <= issued_at <= clock")
    provenance = record["provenance"]
    if provenance not in {"live", "archive", "synthetic"}:
        raise ValueError("provenance must be live, archive or synthetic")
    variant = _text(record["variant"], "variant")
    if variant == "persistence":
        raise ValueError("persistence is reserved for the evaluator's causal baseline")
    result.update(
        {
            "variant": variant,
            "issued_at": iso(issued),
            "inputs_available_at": iso(inputs),
            "training_end": iso(training),
            "source_sha256": _hash(record["source_sha256"], "source_sha256"),
            "config_sha256": _hash(record["config_sha256"], "config_sha256"),
            "input_sha256": _hash(record["input_sha256"], "input_sha256"),
            "provenance": provenance,
            "source": _text(record["source"], "source"),
        }
    )
    if not isinstance(record["points"], list) or not record["points"]:
        raise ValueError("points must be a nonempty list")
    points = []
    seen = set()
    for point in record["points"]:
        _keys(point, {"target_start", "energy_wh"})
        target = timestamp(point["target_start"], "target_start", hourly=True)
        if target <= issued:
            raise ValueError("forecast target_start must be strictly later than issued_at")
        if check_recording_time and provenance == "live" and target <= now:
            raise ValueError("live forecasts must be recorded before target_start")
        if target in seen:
            raise ValueError("duplicate target_start in forecast")
        seen.add(target)
        points.append(
            {"target_start": iso(target), "energy_wh": _number(point["energy_wh"], "energy_wh")}
        )
    result["points"] = sorted(points, key=lambda p: p["target_start"])
    return result


def normalize_actual(record: dict, now: datetime) -> dict:
    _keys(
        record,
        COMMON
        | {
            "target_start",
            "available_at",
            "energy_wh",
            "quality",
            "daylight",
            "source",
        },
    )
    result = _common(record)
    target = timestamp(record["target_start"], "target_start", hourly=True)
    available = timestamp(record["available_at"], "available_at")
    if not target + HOUR <= available <= timestamp(iso(now), "clock"):
        raise ValueError("require interval end <= available_at <= clock")
    quality = record["quality"]
    if quality not in {"valid", "missing", "curtailed"}:
        raise ValueError("quality must be valid, missing or curtailed")
    if record["daylight"] not in {"day", "night", "unknown"}:
        raise ValueError("daylight must be day, night or unknown")
    value = record["energy_wh"]
    if quality == "missing":
        if value is not None:
            raise ValueError("missing actuals must use null energy_wh")
    else:
        value = _number(value, "energy_wh")
    result.update(
        {
            "target_start": iso(target),
            "available_at": iso(available),
            "energy_wh": value,
            "quality": quality,
            "daylight": record["daylight"],
            "source": _text(record["source"], "source"),
        }
    )
    return result


class ForecastLedger:
    """SQLite evidence store; exact retries are idempotent, conflicts fail.

    UPDATE/DELETE triggers protect against accidental edits. They are not a
    signature or protection against someone controlling the database file.
    """

    def __init__(self, path: str | Path, *, readonly: bool = False):
        self.path = Path(path).expanduser().resolve()
        if readonly:
            self.db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, timeout=10)
        try:
            self._initialize(readonly)
        except Exception:
            self.db.close()
            raise

    def _initialize(self, readonly: bool) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        application = self.db.execute("PRAGMA application_id").fetchone()[0]
        objects = set(
            self.db.execute("SELECT type, name FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'")
        )
        tables = {name for kind, name in objects if kind == "table"}
        if not readonly and not objects and version == 0 and application == 0:
            self.db.execute("BEGIN IMMEDIATE")
            for table in ("forecasts", "actuals"):
                self.db.execute(
                    f"CREATE TABLE {table} ("
                    "key TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                    "sha256 TEXT NOT NULL, recorded_at TEXT NOT NULL)"
                )
                for operation in ("UPDATE", "DELETE"):
                    self.db.execute(
                        f"CREATE TRIGGER {table}_no_{operation.lower()} "
                        f"BEFORE {operation} ON {table} BEGIN "
                        "SELECT RAISE(ABORT, 'ledger is append-only'); END"
                    )
            self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.db.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            self.db.commit()
            return
        if (
            application != APPLICATION_ID
            or version != SCHEMA_VERSION
            or tables != {"forecasts", "actuals"}
            or any(kind not in {"table", "trigger"} for kind, _ in objects)
        ):
            raise ValueError("foreign database or unsupported ledger schema")
        expected_columns = [
            ("key", "TEXT", 0, 1),
            ("payload", "TEXT", 1, 0),
            ("sha256", "TEXT", 1, 0),
            ("recorded_at", "TEXT", 1, 0),
        ]
        for table in sorted(tables):
            columns = [
                (r[1], r[2], r[3], r[5]) for r in self.db.execute(f"PRAGMA table_info({table})")
            ]
            if columns != expected_columns:
                raise ValueError("unsupported ledger table schema")
        triggers = {name for kind, name in objects if kind == "trigger"}
        if triggers != {f"{table}_no_{op}" for table in tables for op in ("update", "delete")}:
            raise ValueError("ledger append-only guards are missing or altered")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def append(self, kind: str, records: list[dict], *, now: datetime | None = None) -> dict:
        if kind not in {"forecasts", "actuals"}:
            raise ValueError("kind must be forecasts or actuals")
        now = now or datetime.now(UTC)
        # Validate everything before opening the write transaction.
        normalized = [
            normalize_forecast(record, now, check_recording_time=False)
            if kind == "forecasts"
            else normalize_actual(record, now)
            for record in records
        ]
        inserted = duplicates = 0
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for record in normalized:
                key_fields = [record["site_id"], record["panel_id"]]
                key_fields += (
                    [record["variant"], record["issued_at"]]
                    if kind == "forecasts"
                    else [record["target_start"]]
                )
                key = canonical(key_fields)
                payload = canonical(record)
                old = self.db.execute(f"SELECT payload FROM {kind} WHERE key=?", (key,)).fetchone()
                if old is not None:
                    if old[0] != payload:
                        raise ValueError(
                            f"conflicting {kind} record; existing evidence is immutable"
                        )
                    duplicates += 1
                    continue
                # A byte-equivalent retry may arrive after the original target;
                # only a previously unseen live prediction needs this clock gate.
                if (
                    kind == "forecasts"
                    and record["provenance"] == "live"
                    and any(
                        timestamp(p["target_start"], "target_start") <= now
                        for p in record["points"]
                    )
                ):
                    raise ValueError("live forecasts must be recorded before target_start")
                self.db.execute(
                    f"INSERT INTO {kind} VALUES (?, ?, ?, ?)",
                    (key, payload, digest(record), iso(now)),
                )
                inserted += 1
        return {"inserted": inserted, "duplicates": duplicates}

    def snapshot(self, as_of: datetime) -> tuple[list[dict], list[dict], str]:
        rows: dict[str, list[dict]] = {}
        evidence = []
        # One read transaction provides a consistent cut even with a live writer.
        with self.db:
            self.db.execute("BEGIN")
            for table in ("forecasts", "actuals"):
                rows[table] = []
                for key, payload, stored_hash, recorded in self.db.execute(
                    f"SELECT key,payload,sha256,recorded_at FROM {table} ORDER BY key"
                ):
                    record = json.loads(payload)
                    if digest(record) != stored_hash:
                        raise ValueError("ledger payload checksum mismatch")
                    if timestamp(recorded, "recorded_at") <= as_of:
                        record["_recorded_at"] = recorded
                        rows[table].append(record)
                        evidence.append([table, key, stored_hash, recorded])
        return rows["forecasts"], rows["actuals"], digest(evidence)


def normalize_plan(plan: dict) -> dict:
    _keys(
        plan,
        {
            "schema_version",
            "site_id",
            "panel_id",
            "timezone",
            "train_end",
            "validation_end",
            "test_end",
            "min_lead_hours",
            "max_lead_hours",
            "variants",
        },
        {"training_policy"},
    )
    if plan["schema_version"] != SCHEMA_VERSION or isinstance(plan["schema_version"], bool):
        raise ValueError("unsupported plan schema_version")
    result = dict(plan)
    result["training_policy"] = plan.get("training_policy", "frozen")
    if result["training_policy"] not in {"frozen", "rolling_origin"}:
        raise ValueError("training_policy must be frozen or rolling_origin")
    for field in ("site_id", "panel_id", "timezone"):
        result[field] = _text(plan[field], field)
    ZoneInfo(result["timezone"])
    bounds = [
        timestamp(plan[k], k, hourly=True) for k in ("train_end", "validation_end", "test_end")
    ]
    if not bounds[0] < bounds[1] < bounds[2]:
        raise ValueError("require train_end < validation_end < test_end")
    for key, value in zip(("train_end", "validation_end", "test_end"), bounds, strict=True):
        result[key] = iso(value)
    for key in ("min_lead_hours", "max_lead_hours"):
        result[key] = _number(plan[key], key)
    if not 0 < result["min_lead_hours"] <= result["max_lead_hours"]:
        raise ValueError("require 0 < min_lead_hours <= max_lead_hours")
    variants = plan["variants"]
    if not isinstance(variants, list) or len(variants) < 2:
        raise ValueError("variants must name at least two comparisons")
    variants = [_text(v, "variant") for v in variants]
    if len(set(variants)) != len(variants):
        raise ValueError("variants must be unique")
    result["variants"] = variants
    return result


def _metrics(pairs: list[tuple[float, float]]) -> dict:
    return _error_metrics([predicted - actual for predicted, actual in pairs])


def _error_metrics(errors: list[float]) -> dict:
    if not errors:
        return {"count": 0, "mae_wh": None, "rmse_wh": None, "bias_wh": None}
    if any(not math.isfinite(error) for error in errors):
        raise ValueError("energy error exceeds finite numeric range")
    scale = max(abs(error) for error in errors) or 1.0
    normalized = [error / scale for error in errors]
    return {
        "count": len(errors),
        "mae_wh": scale * (math.fsum(abs(error) for error in normalized) / len(errors)),
        "rmse_wh": scale
        * math.sqrt(math.fsum(error * error for error in normalized) / len(errors)),
        "bias_wh": scale * (math.fsum(normalized) / len(errors)),
    }


def _daily_error(rows: list, variant: str) -> float:
    try:
        # Sum paired errors, not two potentially overflowing totals. It also
        # avoids losing a small error when two large daily totals nearly cancel.
        return math.fsum(row[2][variant] - row[3]["energy_wh"] for row in rows)
    except OverflowError as exc:
        raise ValueError("daily energy error exceeds finite numeric range") from exc


def evaluate(
    ledger: ForecastLedger,
    plan: dict,
    *,
    as_of: datetime,
    phase: str = "test",
    allow_retrospective: bool = False,
) -> dict:
    """Compare fixed variants on their common issue/target rows, never refit.

    The declared training cutoff must precede the plan's train_end. Test rows
    are never used to tune or select a variant here. External archive provenance
    is an assertion supplied by its producer, not verified causal history.
    """
    plan = normalize_plan(plan)
    as_of = timestamp(iso(as_of), "as_of")
    if phase not in {"validation", "test"}:
        raise ValueError("phase must be validation or test")
    train_end = timestamp(plan["train_end"], "train_end")
    start = timestamp(plan["validation_end"] if phase == "test" else plan["train_end"], "start")
    end = timestamp(plan["test_end"] if phase == "test" else plan["validation_end"], "end")
    forecasts, actual_rows, evidence_hash = ledger.snapshot(as_of)
    variants = plan["variants"]
    selected: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    provenance: Counter[str] = Counter()
    manifests = {}
    forecast_exclusions: Counter[str] = Counter()
    actuals = {
        r["target_start"]: r
        for r in actual_rows
        if r["site_id"] == plan["site_id"] and r["panel_id"] == plan["panel_id"]
    }
    for record in forecasts:
        if (record["site_id"], record["panel_id"]) != (plan["site_id"], plan["panel_id"]):
            continue
        if record["variant"] not in variants:
            continue
        issue = timestamp(record["issued_at"], "issued_at")
        for point in record["points"]:
            target = timestamp(point["target_start"], "target_start")
            lead = (target - issue).total_seconds() / 3600
            if (
                not start <= target < end
                or not plan["min_lead_hours"] <= lead <= plan["max_lead_hours"]
            ):
                continue
            if record["provenance"] != "live" and not allow_retrospective:
                forecast_exclusions[record["provenance"]] += 1
                continue
            if (
                plan["training_policy"] == "frozen"
                and timestamp(record["training_end"], "training_end") > train_end
            ):
                raise ValueError("forecast training_end crosses the fixed training boundary")
            selected[(record["issued_at"], point["target_start"])][record["variant"]] = point[
                "energy_wh"
            ]
            provenance[record["provenance"]] += 1
            manifest = {
                key: record[key]
                for key in (
                    "variant",
                    "issued_at",
                    "training_end",
                    "inputs_available_at",
                    "source_sha256",
                    "config_sha256",
                    "input_sha256",
                    "provenance",
                    "source",
                )
            }
            manifests[digest(manifest)] = manifest

    if "persistence" in variants:
        for (issue_text, target_text), predictions in selected.items():
            issue = timestamp(issue_text, "issued_at")
            target = timestamp(target_text, "target_start")
            # Same UTC hour, most recent available value in the preceding week.
            for days in range(1, 8):
                previous = actuals.get(iso(target - timedelta(days=days)))
                if (
                    previous
                    and previous["quality"] == "valid"
                    and timestamp(previous["available_at"], "available_at") <= issue
                    and (
                        allow_retrospective
                        or timestamp(previous["_recorded_at"], "recorded_at") <= issue
                    )
                ):
                    predictions["persistence"] = previous["energy_wh"]
                    break

    exclusion: Counter[str] = Counter()
    coverage = {
        variant: sum(variant in predictions for predictions in selected.values())
        for variant in variants
    }
    matched: list[tuple[str, str, dict[str, float], dict]] = []
    for (issue_text, target_text), predictions in sorted(selected.items()):
        if any(variant not in predictions for variant in variants):
            exclusion["variant_missing"] += 1
            continue
        actual = actuals.get(target_text)
        if actual is None:
            exclusion["actual_absent"] += 1
        elif timestamp(actual["available_at"], "available_at") > as_of:
            exclusion["actual_not_available"] += 1
        elif actual["quality"] != "valid":
            exclusion[actual["quality"]] += 1
        else:
            matched.append((issue_text, target_text, predictions, actual))

    zone = ZoneInfo(plan["timezone"])
    daily: dict[tuple[str, str], list] = defaultdict(list)
    for row in matched:
        day = timestamp(row[1], "target_start").astimezone(zone).date().isoformat()
        daily[(row[0], day)].append(row)
    complete_days = []
    for (_, day), rows in daily.items():
        midnight = datetime.fromisoformat(day).replace(tzinfo=zone)
        following = midnight + timedelta(days=1)
        if any(boundary.astimezone(UTC).minute for boundary in (midnight, following)):
            raise ValueError("daily metrics require a timezone with whole-hour day boundaries")
        expected = set()
        cursor = midnight.astimezone(UTC)
        while cursor < following.astimezone(UTC):
            expected.add(iso(cursor))
            cursor += HOUR
        if {row[1] for row in rows} == expected:
            complete_days.append(rows)

    metrics = {}
    for variant in variants:

        def pairs(rows, which=variant):
            return [(row[2][which], row[3]["energy_wh"]) for row in rows]

        metrics[variant] = {
            "hourly": _metrics(pairs(matched)),
            "by_daylight": {
                label: _metrics(pairs([r for r in matched if r[3]["daylight"] == label]))
                for label in ("day", "night", "unknown")
            },
            "daily": _error_metrics([_daily_error(rows, variant) for rows in complete_days]),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "evaluated" if matched else "insufficient_data",
        "plan": plan,
        "plan_sha256": digest(plan),
        "evidence_sha256": evidence_hash,
        "as_of": iso(as_of),
        "phase": phase,
        "forecast_manifests": [manifests[key] for key in sorted(manifests)],
        "interval_semantics": "Wh over [target_start, target_start + 1 UTC hour)",
        "bias_sign": "prediction minus actual",
        "provenance_counts": dict(provenance),
        "retrospective_allowed": allow_retrospective,
        "forecast_exclusions": dict(forecast_exclusions),
        "coverage": {
            "union_forecast_rows": len(selected),
            "available_by_variant": coverage,
            "matched_rows": len(matched),
            "matched_fraction": len(matched) / len(selected) if selected else None,
            "excluded_rows": dict(exclusion),
            "complete_issue_days": len(complete_days),
            "incomplete_issue_days": len(daily) - len(complete_days),
        },
        "metrics": metrics,
        "limitations": [
            "Recorded inputs and archive training cutoffs are producer assertions; external fitting is not audited.",
            "Zero and night generation are retained. Missing and curtailed actuals are excluded equally.",
            "Repeated issue times for a target are separate forecast cases, not independent measurements.",
            "Daily scores include complete local days from one issue time only (23/24/25 hours with DST).",
            "No MAPE, automatic winner selection, refitting, scheduling, network or hardware actions.",
        ],
    }


def record_operational_forecasts(
    path: str | Path,
    *,
    base: dict,
    final: dict,
    configuration: dict,
    inputs: dict,
    now: datetime | None = None,
) -> dict:
    """Record future full hours from the completed workflow, before delivery.

    Current/past hours from provider responses are intentionally not backdated
    into the prospective ledger. Both variants share one observation timestamp.
    """
    now = now or datetime.now(UTC)
    source = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("model.py", "workflow.py", "evaluation.py")
    }
    records = []
    skipped = {}
    for variant, forecast in (("base", base), ("final", final)):
        points = [
            {"target_start": p["timestamp"], "energy_wh": p["energy_wh"]}
            for p in forecast["points"]
            if timestamp(p["timestamp"], "timestamp", hourly=True) > now
        ]
        skipped[variant] = len(forecast["points"]) - len(points)
        if not points:
            continue
        records.append(
            {
                "schema_version": 1,
                "site_id": forecast["site_id"],
                "panel_id": forecast["panel_id"] or "all",
                "unit": "Wh",
                "interval_seconds": 3600,
                "variant": variant,
                "issued_at": iso(now),
                "inputs_available_at": iso(now),
                "training_end": iso(now),
                "source_sha256": digest(source),
                "config_sha256": digest(configuration),
                "input_sha256": digest(inputs),
                "provenance": "live",
                "source": "operational workflow snapshot",
                "points": points,
            }
        )
    with ForecastLedger(path) as ledger:
        result = ledger.append("forecasts", records, now=now)
    result["skipped_current_or_past_hours"] = skipped
    return result
