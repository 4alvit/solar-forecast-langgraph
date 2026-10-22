"""Radiation contracts and independent isotropic transposition reference cases."""

import json
import math
from pathlib import Path
from unittest.mock import patch

import pytest

from solar_forecast.config import PanelConfig, SiteConfig
from solar_forecast.model import ForecastMethod, ForecastModel, PhysicalModel, SolarPosition
from solar_forecast.weather import OpenMeteoClient


def panel(tilt=0.0, azimuth=180.0):
    return PanelConfig(
        name="Synthetic panel",
        panel_id="synthetic",
        azimuth=azimuth,
        tilt=tilt,
        capacity_kw=1,
        module_count=1,
        latitude=0,
        longitude=0,
    )


def position(zenith=30.0, azimuth=180.0):
    return SolarPosition(zenith=zenith, azimuth=azimuth, elevation=90 - zenith, air_mass=1.15)


@pytest.mark.parametrize("direct", [600.0, 400.0, 200.0, 1e-10, 0.0])
def test_horizontal_surface_preserves_global_radiation(direct):
    # Exercise the historical keyword too: its existing horizontal meaning stays.
    model = PhysicalModel(panel())
    assert model.calculate_poa_irradiance(
        position(), ghi=800, dni=direct, dhi=800 - direct
    ) == pytest.approx(800)


def test_explicit_horizontal_contract_and_legacy_alias():
    model = PhysicalModel(panel(35))
    expected = model.calculate_poa_irradiance(position(), 800, 600, 200)
    assert (
        model.calculate_poa_irradiance(position(), 800, dhi=200, direct_horizontal=600) == expected
    )
    with pytest.raises(TypeError, match="not both"):
        model.calculate_poa_irradiance(position(), 800, dni=600, dhi=200, direct_horizontal=600)
    with pytest.raises(TypeError, match="required"):
        model.calculate_poa_irradiance(position(), 800, dhi=200)


REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures" / "isotropic-pvlib-0.13.1.json").read_text()
)


@pytest.mark.parametrize("case", REFERENCE["cases"], ids=lambda case: case["name"])
def test_isotropic_transposition_matches_pvlib(case):
    model = PhysicalModel(panel(case["tilt"], case["panel_azimuth"]))
    result = model.calculate_poa_irradiance(
        position(case["zenith"], case["solar_azimuth"]),
        ghi=case["ghi"],
        direct_horizontal=case["direct_horizontal"],
        dhi=case["dhi"],
    )
    assert math.isfinite(result)
    assert result == pytest.approx(case["poa_global"], rel=1e-10, abs=1e-9)


@pytest.mark.parametrize("zenith", [90.0, 100.0])
def test_horizon_and_night_are_zero_even_with_nonzero_hourly_average(zenith):
    assert (
        PhysicalModel(panel(35)).calculate_poa_irradiance(
            position(zenith), ghi=10, direct_horizontal=4, dhi=6
        )
        == 0
    )


@pytest.mark.parametrize("method", list(ForecastMethod))
@pytest.mark.parametrize("cloud", [0, 100])
def test_weather_adapter_to_unfitted_forecast_preserves_diffuse(method, cloud):
    # Real adapter + real physical fallback, fixed geometry, synthetic API response.
    values = {
        "time": "2026-06-21T12:00:00",
        "temperature_2m": 20,
        "relative_humidity_2m": 60,
        "cloud_cover": cloud,
        "cloud_cover_low": cloud,
        "cloud_cover_mid": 0,
        "cloud_cover_high": 0,
        "shortwave_radiation": 800,
        "direct_radiation": 200,
        "diffuse_radiation": 600,
        "wind_speed_10m": 3,
        "wind_direction_10m": 180,
        "pressure_msl": 1013,
    }
    weather = OpenMeteoClient()._parse_response(
        {
            "latitude": 0,
            "longitude": 0,
            "elevation": 0,
            "timezone": "UTC",
            "hourly": {key: [value] for key, value in values.items()},
        }
    )
    config = panel()
    site = SiteConfig(site_name="synthetic", latitude=0, longitude=0, panels=[config])
    model = ForecastModel(site)
    with (
        patch.object(PhysicalModel, "calculate_solar_position", return_value=position()),
        patch.object(
            PhysicalModel,
            "apply_cloud_adjustment",
            side_effect=AssertionError("double cloud derating"),
        ),
    ):
        forecast = model.forecast(weather, method)
    expected = min(
        800 * (1 + config.temperature_coefficient * 5) * config.inverter_efficiency,
        config.capacity_kw * 1000 / config.dc_ac_ratio,
    )
    assert len(forecast.points) == 1
    assert forecast.points[0].power_w == pytest.approx(expected)
    assert forecast.points[0].energy_wh == pytest.approx(expected)
