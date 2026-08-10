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
    ForecastPoint,
    GenerationForecast,
    ForecastModel,
    PhysicalModel,
    StatisticalModel,
    enhance_with_llm,
)
from solar_forecast.weather import OpenMeteoClient, WeatherForecast, WeatherHourly
from solar_forecast.workflow import (
    WorkflowState,
    InverterControlHook,
    build_forecast_workflow,
    run_forecast,
    run_forecast_streaming,
)

__version__ = "0.1.0"

__all__ = [
    # Config
    "PanelConfig",
    "SiteConfig",
    "DEFAULT_SITE",
    # History
    "GenerationRecord",
    "HistoricalData",
    "InverterMonitoringLoader",
    "LocalCSVLoader",
    # Model
    "ForecastMethod",
    "ForecastPoint",
    "GenerationForecast",
    "ForecastModel",
    "PhysicalModel",
    "StatisticalModel",
    "enhance_with_llm",
    # Weather
    "OpenMeteoClient",
    "WeatherForecast",
    "WeatherHourly",
    # Workflow
    "WorkflowState",
    "InverterControlHook",
    "build_forecast_workflow",
    "run_forecast",
    "run_forecast_streaming",
]
