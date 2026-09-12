"""LangGraph workflow for solar forecasting."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta, tzinfo
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

mqtt_publish: ModuleType | None
try:
    import paho.mqtt.publish as mqtt_publish

    MQTT_AVAILABLE = True
except Exception:  # pragma: no cover
    mqtt_publish = None
    MQTT_AVAILABLE = False

from solar_forecast.config import SiteConfig
from solar_forecast.history import (
    HistoricalData,
    InfluxDBGenerationLoader,
    InverterMonitoringLoader,
)
from solar_forecast.model import (
    ForecastMethod,
    ForecastModel,
    GenerationForecast,
)
from solar_forecast.weather import OpenMeteoClient, WeatherForecast


class WorkflowState(BaseModel):
    """State for the forecasting workflow."""

    model_config = {"extra": "allow"}  # Allow dynamic fields

    if TYPE_CHECKING:
        # Runtime scratch state is attached only after successful training.
        _trained_model: ForecastModel | None

    # Input parameters
    site_config: SiteConfig
    panel_id: str | None = None
    forecast_horizon_hours: int = 48
    lookback_days: int = 30

    # Intermediate results
    weather_forecast: WeatherForecast | None = None
    historical_data: HistoricalData | None = None
    historical_df: Any | None = None  # pandas DataFrame

    # Outputs
    base_forecast: GenerationForecast | None = None
    enhanced_forecast: GenerationForecast | None = None
    final_forecast: GenerationForecast | None = None

    # Metadata
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    current_step: str = "initialized"
    completed_steps: list[str] = Field(default_factory=list)


logger = logging.getLogger(__name__)


def _env_bool(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_int_opt(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _in_tou_window(start_hour: int, end_hour: int, now_local: datetime) -> bool:
    """True while panel time is inside [start_hour, end_hour); wraps midnight."""
    if start_hour < 0 or end_hour < 0 or start_hour == end_hour:
        return False
    hour = now_local.hour
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour  # wraps midnight


class InverterControlHook(BaseModel):
    """Hook for inverter-control integration via MQTT."""

    model_config = {"extra": "forbid"}

    enabled: bool = _env_bool("INVERTER_CONTROL_ENABLED")
    mqtt_broker: str = os.getenv("MQTT_BROKER", "localhost")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    site_id: str = os.getenv("SITE_ID", "default")
    pre_charge_threshold_wh: float = _env_float(
        "PRE_CHARGE_THRESHOLD_WH", 6000
    )  # Pre-charge if today's calendar-day forecast < this (Wh)
    # Deprecated: rolling cloudy horizon no longer drives the trigger.
    # Kept for backward-compatible MQTT consumers; payload uses 24.
    cloudy_horizon_hours: int = 24
    tou_start_hour: int | None = _env_int_opt(
        "TOU_EXPENSIVE_START_HOUR"
    )  # Suppress pre-charge during expensive TOU window
    tou_end_hour: int | None = _env_int_opt("TOU_EXPENSIVE_END_HOUR")


async def fetch_weather_node(state: WorkflowState) -> WorkflowState:
    """Fetch weather forecast from OpenMeteo."""
    state.current_step = "fetch_weather"
    panel = (
        state.site_config.panel_by_id(state.panel_id)
        if state.panel_id
        else state.site_config.panels[0]
    )

    client = OpenMeteoClient()
    try:
        if panel is None:
            raise ValueError(f"Unknown panel ID: {state.panel_id}")
        forecast = await client.fetch_forecast(
            latitude=panel.latitude,
            longitude=panel.longitude,
            horizon_hours=state.forecast_horizon_hours,
            timezone=panel.timezone,
        )
        state.weather_forecast = forecast
        state.completed_steps.append("fetch_weather")
    except Exception as e:
        state.errors.append(f"Weather fetch failed: {e}")
    return state


async def fetch_history_node(state: WorkflowState) -> WorkflowState:
    """Fetch historical generation data."""
    state.current_step = "fetch_history"
    panel = (
        state.site_config.panel_by_id(state.panel_id)
        if state.panel_id
        else state.site_config.panels[0]
    )

    # InfluxDB backend when configured; legacy inverter-monitoring API otherwise
    loader: InfluxDBGenerationLoader | InverterMonitoringLoader
    if os.getenv("INFLUX_URL"):
        loader = InfluxDBGenerationLoader()
    else:
        loader = InverterMonitoringLoader()
    end = datetime.now(UTC)
    start = end - timedelta(days=state.lookback_days)

    try:
        history = await loader.fetch_generation(
            site_id=state.site_config.site_name,
            start=start,
            end=end,
            panel_id=state.panel_id,
        )
        state.historical_data = history
        state.historical_df = history.to_dataframe()
        state.completed_steps.append("fetch_history")
    except Exception as e:
        state.warnings.append(f"History fetch failed (will use statistical fallback): {e}")
        state.completed_steps.append("fetch_history")
    return state


async def train_model_node(state: WorkflowState) -> WorkflowState:
    """Train statistical model on historical data."""
    state.current_step = "train_model"

    if state.historical_df is None or state.historical_df.empty:
        state.warnings.append("No historical data available, skipping training")
        state.completed_steps.append("train_model")
        return state

    if state.weather_forecast is None:
        state.errors.append("Weather forecast required for training")
        return state

    panel = (
        state.site_config.panel_by_id(state.panel_id)
        if state.panel_id
        else state.site_config.panels[0]
    )
    model = ForecastModel(state.site_config, state.panel_id)

    # Train on PAST weather matched to generation history; the forecast weather
    # only covers future hours so joining against it always came up empty.
    try:
        if panel is None:
            raise ValueError(f"Unknown panel ID: {state.panel_id}")
        client = OpenMeteoClient()
        past_weather = await client.fetch_forecast(
            latitude=panel.latitude,
            longitude=panel.longitude,
            horizon_hours=1,
            timezone=panel.timezone,
            past_days=state.lookback_days,
        )
        hourly_history = state.historical_df.resample("1h").sum(numeric_only=True)
        model.train(past_weather, hourly_history)
        state._trained_model = model  # persist for generate_forecast_node
        state.completed_steps.append("train_model")
    except Exception as e:
        state.warnings.append(f"Model training failed: {e}")
        state.completed_steps.append("train_model")
    return state


async def generate_forecast_node(state: WorkflowState) -> WorkflowState:
    """Generate base forecast using ensemble method."""
    state.current_step = "generate_forecast"

    if state.weather_forecast is None:
        state.errors.append("Weather forecast required for generation")
        return state

    panel = (
        state.site_config.panel_by_id(state.panel_id)
        if state.panel_id
        else state.site_config.panels[0]
    )
    model = ForecastModel(state.site_config, state.panel_id)

    # Use trained statistical model if available
    if hasattr(state, "_trained_model") and state._trained_model is not None:
        model.statistical = state._trained_model.statistical

    try:
        forecast = model.forecast(state.weather_forecast, method=ForecastMethod.ENSEMBLE)
        state.base_forecast = forecast
        state.completed_steps.append("generate_forecast")
    except Exception as e:
        state.errors.append(f"Forecast generation failed: {e}")
    return state


async def enhance_forecast_node(state: WorkflowState) -> WorkflowState:
    """Enhance forecast with LLM reasoning (placeholder)."""
    state.current_step = "enhance_forecast"

    if state.base_forecast is None:
        state.errors.append("Base forecast required for enhancement")
        return state

    # For now, just pass through - LLM enhancement to be implemented
    from solar_forecast.model import enhance_with_llm

    panel = (
        state.site_config.panel_by_id(state.panel_id)
        if state.panel_id
        else state.site_config.panels[0]
    )

    try:
        if panel is None or state.weather_forecast is None:
            raise ValueError("Panel and weather are required for forecast enhancement")
        enhanced = await enhance_with_llm(
            state.base_forecast,
            state.weather_forecast,
            state.site_config,
            panel,
            state.historical_df,
        )
        state.enhanced_forecast = enhanced
        state.completed_steps.append("enhance_forecast")
    except Exception as e:
        state.warnings.append(f"LLM enhancement failed: {e}")
        state.enhanced_forecast = state.base_forecast
        state.completed_steps.append("enhance_forecast")
    return state


async def inverter_control_hook_node(state: WorkflowState) -> WorkflowState:
    """Send forecast to inverter-control for pre-charge decisions."""
    state.current_step = "inverter_control_hook"

    if state.final_forecast is None:
        state.errors.append("Final forecast required for inverter hook")
        return state

    hook = InverterControlHook()
    if not hook.enabled:
        state.completed_steps.append("inverter_control_hook")
        return state

    # Publish today/tomorrow kWh summary every run for dashboard display
    panel = (
        state.site_config.panel_by_id(state.panel_id)
        if state.panel_id
        else state.site_config.panels[0]
    )

    if panel is None:
        raise ValueError(f"Unknown panel ID: {state.panel_id}")
    local_tz: tzinfo
    # Pre-charge only after 00:01 local (panel TZ), when today's calendar-day
    # forecast total is below threshold. Do not use a rolling N-hour window.
    try:
        local_tz = ZoneInfo(panel.timezone)
    except Exception:
        local_tz = UTC
    now_local = datetime.now(UTC).astimezone(local_tz)
    after_midnight_gate = now_local.hour > 0 or now_local.minute >= 1

    daily = _daily_kwh_by_date(state.final_forecast.points, panel.timezone)
    today_key = now_local.strftime("%Y-%m-%d")
    today_kwh = daily.get(today_key, 0.0)
    today_wh = today_kwh * 1000.0

    if after_midnight_gate and today_wh < hook.pre_charge_threshold_wh:
        if (
            hook.tou_start_hour is not None
            and hook.tou_end_hour is not None
            and _in_tou_window(hook.tou_start_hour, hook.tou_end_hour, now_local)
        ):
            state.warnings.append(
                f"Pre-charge suppressed: expensive grid window "
                f"({hook.tou_start_hour}:00-{hook.tou_end_hour}:00)"
            )
        else:
            state.warnings.append(
                f"Low generation forecast ({today_wh:.0f} Wh for today) - triggering pre-charge"
            )
            await _trigger_pre_charge(hook, today_wh)

    await _post_daily_forecast(hook, state.final_forecast, panel.timezone)

    state.completed_steps.append("inverter_control_hook")
    return state


def _daily_kwh_by_date(points: list, tz_name: str) -> dict[str, float]:
    """Sum forecast energy into kWh totals keyed by local calendar date (YYYY-MM-DD)."""
    tz: tzinfo
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = UTC
    totals: dict[str, float] = {}
    for p in points:
        local_day = p.timestamp.astimezone(tz).strftime("%Y-%m-%d")
        totals[local_day] = totals.get(local_day, 0.0) + p.energy_wh / 1000.0
    return totals


async def _post_daily_forecast(
    hook: InverterControlHook,
    forecast: GenerationForecast,
    timezone_name: str,
) -> None:
    """Publish today/tomorrow kWh summary to N/{site}/solar_forecast/forecast_json (retain)."""
    now_local = datetime.now(UTC).astimezone(ZoneInfo(timezone_name))
    daily = _daily_kwh_by_date(forecast.points, timezone_name)
    today_key = now_local.strftime("%Y-%m-%d")
    tomorrow_key = (now_local + timedelta(days=1)).strftime("%Y-%m-%d")

    payload: dict[str, Any] = {
        "site_id": forecast.site_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "date": today_key,
    }
    if today_key in daily:
        payload["today_kwh"] = round(daily[today_key], 2)
    if tomorrow_key in daily:
        payload["tomorrow_kwh"] = round(daily[tomorrow_key], 2)

    if not MQTT_AVAILABLE or mqtt_publish is None:
        logger.warning("paho-mqtt not available; skipping forecast publish")
        return

    topic = f"N/{hook.site_id}/solar_forecast/forecast_json"
    msg_payload = json.dumps(payload)
    try:
        mqtt_publish.single(
            topic=topic,
            payload=msg_payload,
            hostname=hook.mqtt_broker,
            port=hook.mqtt_port,
            retain=True,
        )
        logger.info(
            "Published forecast to %s on %s:%d (retain=True): %s",
            topic,
            hook.mqtt_broker,
            hook.mqtt_port,
            msg_payload,
        )
    except Exception as e:
        logger.warning(
            "Forecast publish to %s:%d topic %s failed: %s",
            hook.mqtt_broker,
            hook.mqtt_port,
            topic,
            e,
        )


async def _trigger_pre_charge(hook: InverterControlHook, forecast_energy_wh: float) -> None:
    """Publish pre-charge request to N/{site}/solar_forecast/pre_charge_request."""
    if not MQTT_AVAILABLE or mqtt_publish is None:
        logger.warning("paho-mqtt not available; skipping pre-charge publish")
        return

    topic = f"N/{hook.site_id}/solar_forecast/pre_charge_request"
    payload = {
        "trigger": "low_solar_forecast",
        "forecast_energy_wh": forecast_energy_wh,
        "threshold_wh": hook.pre_charge_threshold_wh,
        "horizon_hours": 24,
        "horizon": "next_day",
        "day": "today",
    }
    msg_payload = json.dumps(payload)
    try:
        mqtt_publish.single(
            topic=topic,
            payload=msg_payload,
            hostname=hook.mqtt_broker,
            port=hook.mqtt_port,
            retain=False,
        )
        logger.info(
            "Pre-charge request published to %s on %s:%d: %.0f Wh forecast",
            topic,
            hook.mqtt_broker,
            hook.mqtt_port,
            forecast_energy_wh,
        )
    except Exception as e:
        logger.warning(
            "Pre-charge publish to %s:%d topic %s failed: %s",
            hook.mqtt_broker,
            hook.mqtt_port,
            topic,
            e,
        )


async def finalize_forecast_node(state: WorkflowState) -> WorkflowState:
    """Finalize forecast output."""
    state.current_step = "finalize"

    # Use enhanced if available, else base
    state.final_forecast = state.enhanced_forecast or state.base_forecast

    if state.final_forecast is None:
        state.errors.append("No forecast generated")
    else:
        state.completed_steps.append("finalize")
    return state


def should_continue(state: WorkflowState) -> Literal["continue", "error"]:
    """Determine if workflow should continue or handle error."""
    if state.errors:
        return "error"
    return "continue"


def build_forecast_workflow() -> StateGraph:
    """Build the LangGraph forecasting workflow."""
    workflow = StateGraph(WorkflowState)

    # Add nodes
    workflow.add_node("fetch_weather", fetch_weather_node)
    workflow.add_node("fetch_history", fetch_history_node)
    workflow.add_node("train_model", train_model_node)
    workflow.add_node("generate_forecast", generate_forecast_node)
    workflow.add_node("enhance_forecast", enhance_forecast_node)
    workflow.add_node("inverter_control_hook", inverter_control_hook_node)
    workflow.add_node("finalize_forecast", finalize_forecast_node)

    # Define edges
    workflow.set_entry_point("fetch_weather")

    # Parallel fetch weather and history
    workflow.add_edge("fetch_weather", "fetch_history")

    # Train model after history
    workflow.add_edge("fetch_history", "train_model")

    # Generate forecast after training
    workflow.add_edge("train_model", "generate_forecast")

    # Enhance forecast
    workflow.add_edge("generate_forecast", "enhance_forecast")

    # Finalize before the inverter hook so final_forecast is populated
    # when the pre-charge decision runs
    workflow.add_edge("enhance_forecast", "finalize_forecast")
    workflow.add_edge("finalize_forecast", "inverter_control_hook")
    workflow.add_edge("inverter_control_hook", END)

    return workflow


async def run_forecast(
    site_config: SiteConfig,
    panel_id: str | None = None,
    forecast_horizon_hours: int = 48,
    lookback_days: int = 30,
) -> WorkflowState:
    """Run the complete forecasting workflow."""
    workflow = build_forecast_workflow()
    app = workflow.compile()

    initial_state = WorkflowState(
        site_config=site_config,
        panel_id=panel_id,
        forecast_horizon_hours=forecast_horizon_hours,
        lookback_days=lookback_days,
    )

    result = await app.ainvoke(initial_state)
    return WorkflowState(**result)


async def run_forecast_streaming(
    site_config: SiteConfig,
    panel_id: str | None = None,
    forecast_horizon_hours: int = 48,
    lookback_days: int = 30,
):
    """Run workflow with streaming updates."""
    workflow = build_forecast_workflow()
    app = workflow.compile()

    initial_state = WorkflowState(
        site_config=site_config,
        panel_id=panel_id,
        forecast_horizon_hours=forecast_horizon_hours,
        lookback_days=lookback_days,
    )

    async for step in app.astream(initial_state):
        yield step
