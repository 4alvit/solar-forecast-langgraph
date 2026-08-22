"""LangGraph workflow for solar forecasting."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from solar_forecast.config import SiteConfig
from solar_forecast.history import HistoricalData, InverterMonitoringLoader
from solar_forecast.model import (
    ForecastMethod,
    ForecastModel,
    GenerationForecast,
)
from solar_forecast.weather import OpenMeteoClient, WeatherForecast


class WorkflowState(BaseModel):
    """State for the forecasting workflow."""

    model_config = {"extra": "allow"}  # Allow dynamic fields

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


def _in_tou_window(start_hour: int, end_hour: int) -> bool:
    """True while local time is inside [start_hour, end_hour); wraps midnight."""
    if start_hour < 0 or end_hour < 0 or start_hour == end_hour:
        return False
    hour = datetime.now().astimezone().hour  # local wall-clock hour (container TZ)
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour  # wraps midnight


class InverterControlHook(BaseModel):
    """Hook for inverter-control integration."""

    model_config = {"extra": "forbid"}

    enabled: bool = _env_bool("INVERTER_CONTROL_ENABLED")
    endpoint: str = os.getenv(
        "INVERTER_CONTROL_URL", "http://localhost:8081"
    )  # inverter-control API
    api_key: str | None = os.getenv("INVERTER_CONTROL_API_KEY") or None
    pre_charge_threshold_wh: float = 5000  # Pre-charge if forecast < this
    cloudy_horizon_hours: int = 6  # Hours to look ahead for cloudy period
    webhook_url: str | None = None  # Alternative: push to webhook
    tou_start_hour: int | None = _env_int_opt(
        "TOU_EXPENSIVE_START_HOUR"
    )  # expensive window start (local hour), disabled when unset
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

    try:
        model.train(state.weather_forecast, state.historical_df)
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

    # Check for cloudy period in near future (exclude past points; the weather
    # fetch includes past_hours=1)
    now = datetime.now(UTC)
    horizon_end = now + timedelta(hours=hook.cloudy_horizon_hours)
    near_future = [p for p in state.final_forecast.points if now <= p.timestamp <= horizon_end]

    if near_future:
        total_near_energy = sum(p.energy_wh for p in near_future)
        if total_near_energy < hook.pre_charge_threshold_wh:
            if (
                hook.tou_start_hour is not None
                and hook.tou_end_hour is not None
                and _in_tou_window(hook.tou_start_hour, hook.tou_end_hour)
            ):
                state.warnings.append(
                    f"Pre-charge suppressed: expensive grid window "
                    f"({hook.tou_start_hour}:00-{hook.tou_end_hour}:00)"
                )
            else:
                state.warnings.append(
                    f"Low generation forecast ({total_near_energy:.0f} Wh in {hook.cloudy_horizon_hours}h) - "
                    f"triggering pre-charge"
                )
                await _trigger_pre_charge(hook, total_near_energy)

    state.completed_steps.append("inverter_control_hook")
    return state


async def _trigger_pre_charge(hook: InverterControlHook, forecast_energy_wh: float) -> None:
    """Call inverter-control API to trigger battery pre-charge."""
    url = f"{hook.endpoint.rstrip('/')}/api/v1/pre-charge"
    headers = {"Content-Type": "application/json"}
    if hook.api_key:
        headers["Authorization"] = f"Bearer {hook.api_key}"

    payload = {
        "trigger": "low_solar_forecast",
        "forecast_energy_wh": forecast_energy_wh,
        "threshold_wh": hook.pre_charge_threshold_wh,
        "horizon_hours": hook.cloudy_horizon_hours,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info("Pre-charge triggered at %s: %.0f Wh forecast", url, forecast_energy_wh)
    except httpx.HTTPError as e:
        # Log but don't fail workflow - pre-charge is optional
        logger.warning("Pre-charge call to %s failed: %s", url, e)


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
