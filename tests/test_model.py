"""Tests for model module."""

import asyncio
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from solar_forecast.config import PanelConfig, SiteConfig
from solar_forecast.model import (
    ForecastMethod,
    ForecastModel,
    ForecastPoint,
    GenerationForecast,
    PhysicalModel,
    StatisticalModel,
    enhance_with_llm,
)
from solar_forecast.weather import WeatherForecast, WeatherHourly


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
    np.random.seed(42)  # Fixed seed for reproducibility
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

    np.random.seed(42)  # Fixed seed for reproducibility
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


def test_physical_model_cloud_adjustment_low():
    """Test cloud adjustment with low cloud type."""
    site = create_test_site()
    panel = site.panels[0]
    physical = PhysicalModel(panel)

    clear_power = 3000.0

    # Low clouds block more
    adjusted = physical.apply_cloud_adjustment(clear_power, 50, cloud_type="low")
    assert adjusted < clear_power
    assert adjusted > 0


def test_physical_model_cloud_adjustment_high():
    """Test cloud adjustment with high cloud type."""
    site = create_test_site()
    panel = site.panels[0]
    physical = PhysicalModel(panel)

    clear_power = 3000.0

    # High clouds block less
    adjusted = physical.apply_cloud_adjustment(clear_power, 50, cloud_type="high")
    assert adjusted < clear_power
    assert adjusted > 0

    # High clouds should allow more power than low clouds at same cover
    adjusted_low = physical.apply_cloud_adjustment(clear_power, 50, cloud_type="low")
    assert adjusted > adjusted_low


def test_physical_model_cloud_adjustment_mid():
    """Test cloud adjustment with mid cloud type (uses total cloud logic)."""
    site = create_test_site()
    panel = site.panels[0]
    physical = PhysicalModel(panel)

    clear_power = 3000.0

    # Mid clouds use total logic (default)
    adjusted = physical.apply_cloud_adjustment(clear_power, 50, cloud_type="mid")
    assert adjusted < clear_power
    assert adjusted > 0


def test_statistical_model_fit_insufficient_data():
    """Test fit raises error with insufficient data."""
    site = create_test_site()
    stat = StatisticalModel()
    weather = create_test_weather_forecast(10)  # Only 10 hours

    hist_rows = []
    for h in weather.hourly:
        gen = max(0, h.shortwave_radiation * 4.5)
        hist_rows.append({"timestamp": h.time, "energy_wh": gen})

    hist_df = pd.DataFrame(hist_rows)
    hist_df.set_index("timestamp", inplace=True)

    with pytest.raises(ValueError, match="Insufficient training data"):
        stat.fit(weather, hist_df)


def test_statistical_model_predict_not_fitted():
    """Test predict raises error when model not fitted."""
    stat = StatisticalModel()
    weather = create_test_weather_forecast(24)

    with pytest.raises(RuntimeError, match="Model not fitted"):
        stat.predict(weather)


def test_forecast_model_with_panel_id():
    """Test ForecastModel with specific panel_id."""
    panel1 = PanelConfig(
        name="Panel 1",
        panel_id="p1",
        azimuth=180,
        tilt=35,
        capacity_kw=5.0,
        module_count=14,
        latitude=52.37,
        longitude=4.90,
    )
    panel2 = PanelConfig(
        name="Panel 2",
        panel_id="p2",
        azimuth=270,
        tilt=30,
        capacity_kw=3.0,
        module_count=8,
        latitude=52.37,
        longitude=4.90,
    )
    site = SiteConfig(
        site_name="test-site",
        latitude=52.37,
        longitude=4.90,
        panels=[panel1, panel2],
    )

    # Model with panel_id should use that panel
    model = ForecastModel(site, panel_id="p2")
    assert model.panel.panel_id == "p2"
    assert model.panel.capacity_kw == 3.0


def test_forecast_model_statistical_method():
    """Test forecast with STATISTICAL method."""
    site = create_test_site()
    model = ForecastModel(site)

    # Need to train first
    train_weather = create_test_weather_forecast(100)
    np.random.seed(42)
    hist_rows = []
    for h in train_weather.hourly:
        gen = max(0, h.shortwave_radiation * 4.5 + np.random.normal(0, 100))
        hist_rows.append({"timestamp": h.time, "energy_wh": gen})

    hist_df = pd.DataFrame(hist_rows)
    hist_df.set_index("timestamp", inplace=True)
    model.train(train_weather, hist_df)

    # Now forecast with STATISTICAL method
    weather = create_test_weather_forecast(24)
    forecast = model.forecast(weather, method=ForecastMethod.STATISTICAL)

    assert forecast.method == ForecastMethod.STATISTICAL
    assert len(forecast.points) == 24
    assert forecast.total_energy_wh() > 0


def test_enhance_with_llm():
    """Test LLM enhancement function."""

    site = create_test_site()
    panel = site.panels[0]

    points = [
        ForecastPoint(
            timestamp=datetime(2024, 6, 15, h, 0, tzinfo=UTC),
            energy_wh=1000.0,
            power_w=1000.0,
            confidence_lower=800.0,
            confidence_upper=1200.0,
            method=ForecastMethod.ENSEMBLE,
        )
        for h in range(6, 18)
    ]

    base_forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=12,
        points=points,
        method=ForecastMethod.ENSEMBLE,
    )

    weather = create_test_weather_forecast(12)
    hist_df = pd.DataFrame(
        {"energy_wh": [1000.0] * 12},
        index=[datetime(2024, 6, 15, h, 0, tzinfo=UTC) for h in range(6, 18)],
    )

    enhanced = asyncio.run(enhance_with_llm(base_forecast, weather, site, panel, hist_df))

    assert enhanced.method == ForecastMethod.LLM_ENHANCED
    assert len(enhanced.points) == 12
    assert enhanced.model_version == "0.1.0+llm"


def test_enhance_with_llm_no_historical():
    """Test LLM enhancement without historical data."""

    site = create_test_site()
    panel = site.panels[0]

    points = [
        ForecastPoint(
            timestamp=datetime(2024, 6, 15, h, 0, tzinfo=UTC),
            energy_wh=1000.0,
            power_w=1000.0,
            confidence_lower=800.0,
            confidence_upper=1200.0,
            method=ForecastMethod.ENSEMBLE,
        )
        for h in range(6, 18)
    ]

    base_forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=12,
        points=points,
        method=ForecastMethod.ENSEMBLE,
    )

    weather = create_test_weather_forecast(12)

    enhanced = asyncio.run(enhance_with_llm(base_forecast, weather, site, panel, None))

    assert enhanced.method == ForecastMethod.LLM_ENHANCED
