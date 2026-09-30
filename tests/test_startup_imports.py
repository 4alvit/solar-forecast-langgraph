"""CLI help and the physical fallback do not need the statistical stack."""

import subprocess
import sys
from pathlib import Path

import pytest

BLOCK_STATISTICAL_IMPORTS = """
import importlib.abc
import socket
import sys
def reject_network(*args, **kwargs):
    raise AssertionError('network forbidden in startup regression')
socket.create_connection = reject_network
socket.socket.connect = reject_network
socket.socket.connect_ex = reject_network
socket.socket.sendto = reject_network
class RejectStatisticalImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sklearn', 'scipy'}:
            raise AssertionError('unexpected statistical import: ' + fullname)
sys.meta_path.insert(0, RejectStatisticalImports())
"""

NO_HISTORY_FORECAST = """
import asyncio
from datetime import UTC, datetime, timedelta
from solar_forecast.config import DEFAULT_SITE
from solar_forecast.weather import WeatherForecast, WeatherHourly
from solar_forecast.workflow import WorkflowState, train_model_node, generate_forecast_node

weather = WeatherForecast(latitude=DEFAULT_SITE.latitude, longitude=DEFAULT_SITE.longitude,
    elevation=0, timezone='UTC', hourly=[WeatherHourly(
        time=datetime(2024,6,15,tzinfo=UTC)+timedelta(hours=h), temperature_2m=20,
        relative_humidity_2m=60, cloud_cover=20, cloud_cover_low=5, cloud_cover_mid=10,
        cloud_cover_high=5, shortwave_radiation=800, direct_radiation=600,
        diffuse_radiation=200, wind_speed_10m=3, wind_direction_10m=180, pressure_msl=1013
    ) for h in range(48)])
state = WorkflowState(site_config=DEFAULT_SITE, weather_forecast=weather)
async def forecast():
    await train_model_node(state)
    await generate_forecast_node(state)
asyncio.run(forecast())
assert not state.errors, state.errors
assert 'No historical data available, skipping training' in state.warnings
assert state.base_forecast is not None
assert len(state.base_forecast.points) == 48
assert state.base_forecast.total_energy_wh() > 0
assert not any(name.split('.')[0] in {'sklearn','scipy'} for name in sys.modules)
"""


@pytest.mark.parametrize(
    "scenario",
    [
        (
            "import runpy; sys.argv=['solar-forecast','--help']; "
            "runpy.run_module('solar_forecast.main',run_name='__main__')"
        ),
        NO_HISTORY_FORECAST,
    ],
    ids=["cli_help", "no_history_forecast"],
)
def test_startup_paths_without_statistical_imports(scenario):
    result = subprocess.run(
        [sys.executable, "-B", "-c", BLOCK_STATISTICAL_IMPORTS + scenario],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_training_preserves_scaler_assignment_and_predictions():
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LinearRegression
    from sklearn.preprocessing import StandardScaler
    from test_model import create_test_weather_forecast

    from solar_forecast.config import DEFAULT_SITE
    from solar_forecast.model import ForecastMethod, ForecastModel

    weather = create_test_weather_forecast(48)
    historical = pd.DataFrame(
        {"energy_wh": [max(0, hour.shortwave_radiation * 4.5) for hour in weather.hourly]},
        index=pd.to_datetime([hour.time for hour in weather.hourly], utc=True),
    )
    model = ForecastModel(DEFAULT_SITE)
    # Callers can still supply their own scaler before fitting.
    scaler = StandardScaler(with_mean=False)
    model.statistical.scaler = scaler
    features = model.statistical.prepare_features(weather).values
    reference_scaler = StandardScaler(with_mean=False)
    scaled = reference_scaler.fit_transform(features)
    reference = LinearRegression().fit(scaled, historical["energy_wh"].values)
    expected = np.maximum(reference.predict(scaled), 0)

    model.train(weather, historical)
    assert model.statistical.scaler is scaler
    assert model.statistical.scaler is model.statistical.scaler
    np.testing.assert_allclose(model.statistical.scaler.scale_, reference_scaler.scale_, rtol=1e-14)
    np.testing.assert_allclose(model.statistical.predict(weather), expected, rtol=1e-12, atol=1e-9)
    forecast = model.forecast(weather, method=ForecastMethod.STATISTICAL)
    np.testing.assert_allclose(
        [p.energy_wh for p in forecast.points], expected, rtol=1e-12, atol=1e-9
    )
