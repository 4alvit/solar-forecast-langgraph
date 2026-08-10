"""Tests for model module."""

import numpy as np
import pandas as pd

from solar_forecast.config import PanelConfig, SiteConfig
from solar_forecast.model import (
    ForecastMethod,
    ForecastPoint,
    GenerationForecast,
    PhysicalModel,
    StatisticalModel,
    ForecastModel,
)
from solar_forecast.weather import WeatherForecast, WeatherHourly
from datetime import UTC, datetime


def create_test_site():
    """Create a test site config."""
    panel = PanelConfig(
        name="Test Panel",
        panel_id="test-1",
        azimuth=180,
        tilt=35,
        capacity_kw=5.0,
        module_count=14,
        latitude=52.37,
        longitude=4.90,
    )
    return SiteConfig(
        site_name="test-site",
        latitude=52.37,
        longitude=4.90,
        panels=[panel],
    )


def create_test_weather_forecast(hours=24):
    """Create a test weather forecast."""
    hourly = []
    base_time = datetime(2024, 6, 15, 6, 0, tzinfo=UTC)  # Summer solstice
    for i in range(hours):
        dt = base_time.replace(hour=(6 + i) % 24)
        # Simulate solar day: peak at noon
        hour = (6 + i) % 24
        ghi = max(0, 800 * np.sin(np.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0
        dni = max(0, 600 * np.sin(np.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0
        dhi = ghi * 0.2

        hourly.append(
            WeatherHourly(
                time=dt,
                temperature_2m=20 + 5 * np.sin(np.pi * (hour - 6) / 12),
                relative_humidity_2m=60,
                cloud_cover=20,
                cloud_cover_low=5,
                cloud_cover_mid=10,
                cloud_cover_high=5,
                shortwave_radiation=ghi,
                direct_radiation=dni,
                diffuse_radiation=dhi,
                wind_speed_10m=3.0,
                wind_direction_10m=180,
                pressure_msl=1013.25,
            )
        )

    return WeatherForecast(
        latitude=52.37,
        longitude=4.90,
        elevation=0,
        timezone="UTC",
        hourly=hourly,
    )


def test_physical_model_solar_position():
    site = create_test_site()
    panel = site.panels[0]
    physical = PhysicalModel(panel)

    # Noon on summer solstice
    dt = datetime(2024, 6, 21, 12, 0, tzinfo=UTC)
    pos = physical.calculate_solar_position(dt, site.latitude, site.longitude)

    assert pos.elevation > 0  # Sun above horizon
    assert 0 <= pos.azimuth <= 360
    assert pos.zenith == 90 - pos.elevation
    assert pos.air_mass > 0


def test_physical_model_poa_irradiance():
    site = create_test_site()
    panel = site.panels[0]
    physical = PhysicalModel(panel)

    # Direct sun at noon
    dt = datetime(2024, 6, 21, 12, 0, tzinfo=UTC)
    pos = physical.calculate_solar_position(dt, site.latitude, site.longitude)

    # Clear sky
    poa = physical.calculate_poa_irradiance(pos, ghi=800, dni=700, dhi=100)
    assert poa > 600  # Should be close to direct for perpendicular

    # Night
    dt_night = datetime(2024, 6, 21, 0, 0, tzinfo=UTC)
    pos_night = physical.calculate_solar_position(dt_night, site.latitude, site.longitude)
    poa_night = physical.calculate_poa_irradiance(pos_night, ghi=0, dni=0, dhi=0)
    assert poa_night == 0


def test_physical_model_clear_sky():
    site = create_test_site()
    panel = site.panels[0]
    physical = PhysicalModel(panel)

    dt = datetime(2024, 6, 21, 12, 0, tzinfo=UTC)
    pos = physical.calculate_solar_position(dt, site.latitude, site.longitude)
    poa = physical.calculate_poa_irradiance(pos, ghi=800, dni=700, dhi=100)

    power = physical.predict_clear_sky(pos, poa)
    assert 0 < power <= 5000  # Within panel capacity


def test_physical_model_cloud_adjustment():
    site = create_test_site()
    panel = site.panels[0]
    physical = PhysicalModel(panel)

    clear_power = 3000.0

    # No clouds
    adjusted = physical.apply_cloud_adjustment(clear_power, 0)
    assert adjusted == clear_power

    # Overcast
    adjusted = physical.apply_cloud_adjustment(clear_power, 100)
    assert adjusted < clear_power
    assert adjusted > 0  # Never zero (diffuse)


def test_statistical_model_prepare_features():
    site = create_test_site()
    stat = StatisticalModel()
    weather = create_test_weather_forecast(48)

    features = stat.prepare_features(weather)
    assert len(features) == 48
    assert "hour" in features.columns
    assert "ghi" in features.columns
    assert "cloud_cover" in features.columns


def test_statistical_model_fit():
    site = create_test_site()
    stat = StatisticalModel()
    weather = create_test_weather_forecast(100)

    # Create synthetic historical data aligned with weather
    hist_rows = []
    for h in weather.hourly:
        # Generation roughly follows GHI with noise
        gen = max(0, h.shortwave_radiation * 4.5 + np.random.normal(0, 100))
        hist_rows.append({"timestamp": h.time, "energy_wh": gen})

    hist_df = pd.DataFrame(hist_rows)
    hist_df.set_index("timestamp", inplace=True)

    stat.fit(weather, hist_df)
    assert stat.is_fitted
    assert stat.model is not None


def test_statistical_model_predict():
    site = create_test_site()
    stat = StatisticalModel()
    weather = create_test_weather_forecast(100)

    hist_rows = []
    for h in weather.hourly:
        gen = max(0, h.shortwave_radiation * 4.5 + np.random.normal(0, 100))
        hist_rows.append({"timestamp": h.time, "energy_wh": gen})

    hist_df = pd.DataFrame(hist_rows)
    hist_df.set_index("timestamp", inplace=True)

    stat.fit(weather, hist_df)

    # Predict on new weather
    new_weather = create_test_weather_forecast(24)
    preds = stat.predict(new_weather)
    assert len(preds) == 24
    assert all(p >= 0 for p in preds)


def test_forecast_model_ensemble():
    site = create_test_site()
    model = ForecastModel(site)

    weather = create_test_weather_forecast(48)
    forecast = model.forecast(weather, method=ForecastMethod.ENSEMBLE)

    assert isinstance(forecast, GenerationForecast)
    assert forecast.site_id == "test-site"
    assert forecast.method == ForecastMethod.ENSEMBLE
    assert len(forecast.points) == 48
    assert forecast.total_energy_wh() > 0


def test_forecast_model_physical_only():
    site = create_test_site()
    model = ForecastModel(site)

    weather = create_test_weather_forecast(24)
    forecast = model.forecast(weather, method=ForecastMethod.PHYSICAL)

    assert forecast.method == ForecastMethod.PHYSICAL
    assert len(forecast.points) == 24


def test_generation_forecast_total():
    points = [
        ForecastPoint(
            timestamp=datetime(2024, 1, 15, h, 0, tzinfo=UTC),
            energy_wh=1000.0,
            power_w=1000.0,
            confidence_lower=800.0,
            confidence_upper=1200.0,
            method=ForecastMethod.ENSEMBLE,
        )
        for h in range(10)
    ]

    forecast = GenerationForecast(
        site_id="test",
        panel_id="p1",
        forecast_horizon_hours=10,
        points=points,
        method=ForecastMethod.ENSEMBLE,
    )

    assert forecast.total_energy_wh() == 10000.0


def test_forecast_model_to_dataframe():
    site = create_test_site()
    model = ForecastModel(site)

    weather = create_test_weather_forecast(12)
    forecast = model.forecast(weather)

    df = forecast.to_dataframe()
    assert len(df) == 12
    assert "timestamp" in df.columns
    assert "energy_wh" in df.columns
    assert "power_w" in df.columns
