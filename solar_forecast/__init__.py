"""Solar Forecast LangGraph - Main package."""

from __future__ import annotations

from solar_forecast.config import DEFAULT_SITE, PanelConfig, SiteConfig
from solar_forecast.history import (
    GenerationRecord,
    HistoricalData,
    InverterMonitoringLoader,
    LocalCSVLoader,
)
from solar_forecast.model import (
    ForecastMethod,
    ForecastModel,
    ForecastPoint,
    GenerationForecast,
    PhysicalModel,
    StatisticalModel,
    enhance_with_llm,
)
from solar_forecast.weather import OpenMeteoClient, WeatherForecast, WeatherHourly
from solar_forecast.workflow import (
    InverterControlHook,
    WorkflowState,
    build_forecast_workflow,
    fetch_history_node,
    fetch_weather_node,
    finalize_forecast_node,
    generate_forecast_node,
    run_forecast,
    run_forecast_streaming,
    train_model_node,
)

__version__ = "0.1.0"

__all__ = [
    # Config
    "DEFAULT_SITE",
    "PanelConfig",
    "SiteConfig",
    # History
    "GenerationRecord",
    "HistoricalData",
    "InverterMonitoringLoader",
    "LocalCSVLoader",
    # Model
    "ForecastMethod",
    "ForecastModel",
    "ForecastPoint",
    "GenerationForecast",
    "PhysicalModel",
    "StatisticalModel",
    "enhance_with_llm",
    # Weather
    "OpenMeteoClient",
    "WeatherForecast",
    "WeatherHourly",
    # Workflow
    "InverterControlHook",
    "WorkflowState",
    "build_forecast_workflow",
    "fetch_history_node",
    "fetch_weather_node",
    "finalize_forecast_node",
    "generate_forecast_node",
    "run_forecast",
    "run_forecast_streaming",
    "train_model_node",
]
