"""The CLI and Python package report the installed distribution's identity."""

import subprocess
import sys
from importlib import import_module
from importlib.metadata import version

import pytest

import solar_forecast


def test_cli_reports_installed_distribution_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "solar_forecast.main", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert (
        result.stdout.strip() == f"solar-forecast-langgraph {version('solar-forecast-langgraph')}"
    )
    assert result.stderr == ""


@pytest.mark.parametrize("argument", ["--version", "--help"])
def test_cli_metadata_paths_do_not_load_forecast_dependencies(argument: str) -> None:
    script = """
import importlib.abc
import runpy
import sys

class NoForecastStack(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            'solar_forecast.config', 'solar_forecast.history', 'solar_forecast.model',
            'solar_forecast.weather', 'solar_forecast.workflow', 'numpy', 'pandas',
            'sklearn', 'langgraph', 'langchain_core',
        }:
            raise AssertionError('CLI metadata imported forecast dependency: ' + fullname)

sys.meta_path.insert(0, NoForecastStack())
runpy.run_module('solar_forecast.main', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, argument],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (
        "Solar Forecast LangGraph" in result.stdout or "solar-forecast-langgraph" in result.stdout
    )
    assert result.stderr == ""


def test_lazy_exports_preserve_the_public_api_and_module_identity() -> None:
    expected = {
        "config": {"DEFAULT_SITE", "PanelConfig", "SiteConfig"},
        "history": {
            "GenerationRecord",
            "HistoricalData",
            "InverterMonitoringLoader",
            "LocalCSVLoader",
        },
        "model": {
            "ForecastMethod",
            "ForecastModel",
            "ForecastPoint",
            "GenerationForecast",
            "PhysicalModel",
            "StatisticalModel",
            "enhance_with_llm",
        },
        "weather": {"OpenMeteoClient", "WeatherForecast", "WeatherHourly"},
        "workflow": {
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
        },
    }
    names = set().union(*expected.values())
    assert set(solar_forecast.__all__) == names
    assert names <= set(dir(solar_forecast))
    for module_name, exports in expected.items():
        module = import_module(f"solar_forecast.{module_name}")
        for name in exports:
            assert getattr(solar_forecast, name) is getattr(module, name)
    namespace: dict = {}
    # The fixed import exercises Python's star-export protocol, without user input.
    exec("from solar_forecast import *", namespace)  # noqa: S102
    assert all(namespace[name] is getattr(solar_forecast, name) for name in names)
    with pytest.raises(AttributeError, match="does_not_exist"):
        _ = solar_forecast.does_not_exist


@pytest.mark.parametrize("installed_version", ["9.8.7rc2", None])
def test_package_and_cli_share_metadata_without_running_forecast(
    installed_version: str | None,
) -> None:
    # A fresh interpreter observes mocked installed metadata before package import.
    # This proves the next release cannot silently keep an old literal version.
    script = f"""
import importlib.metadata
from unittest.mock import patch

original_version = importlib.metadata.version
installed_version = {installed_version!r}

def selected_version(name):
    if name != 'solar-forecast-langgraph':
        return original_version(name)
    if installed_version is None:
        raise importlib.metadata.PackageNotFoundError(name)
    return installed_version

with patch.object(importlib.metadata, 'version', side_effect=selected_version) as read_version:
    import solar_forecast
    import solar_forecast.main as cli
    assert solar_forecast.__version__ == {installed_version or "0+unknown"!r}
    read_version.assert_any_call('solar-forecast-langgraph')

with patch.object(cli, 'load_site_config', side_effect=AssertionError('must not run forecast')):
    cli.main()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == f"solar-forecast-langgraph {installed_version or '0+unknown'}"
    assert result.stderr == ""
