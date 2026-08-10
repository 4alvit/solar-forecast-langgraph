"""LangGraph workflow for solar forecasting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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


class InverterControlHook(BaseModel):
    """Hook for inverter-control integration."""

    model_config = {"extra": "forbid"}

    enabled: bool = True
    endpoint: str = "http://localhost:8081"  # inverter-control API
    api_key: str | None = None
    pre_charge_threshold_wh: float = 5000  # Pre-charge if forecast < this
    cloudy_horizon_hours: int = 6  # Hours to look ahead for cloudy period
    webhook_url: str | None = None  # Alternative: push to webhook


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

    # Check for cloudy period in near future
    near_future = [
        p
        for p in state.final_forecast.points
        if p.timestamp <= datetime.now(UTC) + timedelta(hours=hook.cloudy_horizon_hours)
    ]

    if near_future:
        total_near_energy = sum(p.energy_wh for p in near_future)
        if total_near_energy < hook.pre_charge_threshold_wh:
            state.warnings.append(
                f"Low generation forecast ({total_near_energy:.0f} Wh in {hook.cloudy_horizon_hours}h) - "
                f"triggering pre-charge"
            )
            # TODO: Call inverter-control API to pre-charge battery
            # async with httpx.AsyncClient() as client:
            #     await client.post(f"{hook.endpoint}/api/v1/pre-charge", ...)

    state.completed_steps.append("inverter_control_hook")
    return state


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

    # Inverter control hook
    workflow.add_edge("enhance_forecast", "inverter_control_hook")

    # Finalize
    workflow.add_edge("inverter_control_hook", "finalize_forecast")
    workflow.add_edge("finalize_forecast", END)

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
