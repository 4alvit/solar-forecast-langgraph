"""Solar Forecast LangGraph - Main package."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

try:
    __version__ = version("solar-forecast-langgraph")
except PackageNotFoundError:
    # An unpackaged source checkout has no installed release identity.
    __version__ = "0+unknown"

__all__ = [
    "DEFAULT_SITE",
    "ForecastMethod",
    "ForecastModel",
    "ForecastPoint",
    "GenerationForecast",
    "GenerationRecord",
    "HistoricalData",
    "InverterControlHook",
    "InverterMonitoringLoader",
    "LocalCSVLoader",
    "OpenMeteoClient",
    "PanelConfig",
    "PhysicalModel",
    "SiteConfig",
    "StatisticalModel",
    "WeatherForecast",
    "WeatherHourly",
    "WorkflowState",
    "build_forecast_workflow",
    "enhance_with_llm",
    "fetch_history_node",
    "fetch_weather_node",
    "finalize_forecast_node",
    "generate_forecast_node",
    "run_forecast",
    "run_forecast_streaming",
    "train_model_node",
]


_EXPORT_MODULES = {
    name: module
    for module, names in {
        "config": ("DEFAULT_SITE", "PanelConfig", "SiteConfig"),
        "history": (
            "GenerationRecord",
            "HistoricalData",
            "InverterMonitoringLoader",
            "LocalCSVLoader",
        ),
        "model": (
            "ForecastMethod",
            "ForecastModel",
            "ForecastPoint",
            "GenerationForecast",
            "PhysicalModel",
            "StatisticalModel",
            "enhance_with_llm",
        ),
        "weather": ("OpenMeteoClient", "WeatherForecast", "WeatherHourly"),
        "workflow": (
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
        ),
    }.items()
    for name in names
}


def __getattr__(name: str) -> Any:
    """Load the public forecasting API only when a caller requests it."""
    module = _EXPORT_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
