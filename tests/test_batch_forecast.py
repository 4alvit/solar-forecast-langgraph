"""Batch inference matches the original per-hour forecast calculation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from test_model import create_test_site, create_test_weather_forecast

from solar_forecast.model import ForecastMethod, ForecastModel


def weather_for_hours(hours, *, day=15):
    weather = create_test_weather_forecast(hours)
    start = datetime(2024, 6, day, tzinfo=UTC)
    for i, hour in enumerate(weather.hourly):
        hour.time = start + timedelta(hours=i)
        # Vary the feature columns independently across days, not just by hour.
        hour.cloud_cover = (i * 17) % 101
        hour.temperature_2m += (i % 7) * 0.7
        hour.wind_speed_10m += (i % 5) * 0.3
        hour.shortwave_radiation *= 1 - hour.cloud_cover / 200
    return weather


def trained_model():
    model = ForecastModel(create_test_site())
    weather = weather_for_hours(168, day=1)
    history = pd.DataFrame(
        {
            "energy_wh": [
                4.1 * h.shortwave_radiation + 2 * h.temperature_2m - 70 for h in weather.hourly
            ]
        },
        index=pd.to_datetime([h.time for h in weather.hourly], utc=True),
    )
    model.train(weather, history)
    return model


def per_hour_reference(model, weather, method):
    """Original faeaa43 per-hour path, independent of ForecastModel.forecast."""
    rows = []
    for hour in weather.hourly:
        physical = 0.0
        for component in model.physicals:
            position = component.calculate_solar_position(
                hour.time, model.site_config.latitude, model.site_config.longitude
            )
            irradiance = component.calculate_poa_irradiance(
                position, hour.shortwave_radiation, hour.direct_radiation, hour.diffuse_radiation
            )
            physical += component.predict_clear_sky(position, irradiance)
        statistical = physical
        if model.statistical.is_fitted:
            one_hour = weather.model_copy(update={"hourly": [hour]})
            statistical = model.statistical.predict(one_hour)[0]
        if method == ForecastMethod.ENSEMBLE:
            power = 0.6 * physical + 0.4 * statistical
        elif method == ForecastMethod.STATISTICAL:
            power = statistical
        else:
            power = physical
        energy = power * 1.0
        uncertainty = 0.2 * energy
        rows.append(
            [max(0, energy), max(0, power), max(0, energy - uncertainty), energy + uncertainty]
        )
    return np.array(rows).reshape(-1, 4)


@pytest.mark.parametrize("hours", [0, 1, 24, 48, 192])
@pytest.mark.parametrize("method", list(ForecastMethod))
def test_trained_forecast_matches_original_per_hour_path(hours, method):
    model = trained_model()
    weather = weather_for_hours(hours)
    # Order is contractual even if an upstream provider returns unsorted hours.
    weather.hourly.reverse()
    expected = per_hour_reference(model, weather, method)
    with patch.object(model.statistical, "predict", wraps=model.statistical.predict) as predict:
        result = model.forecast(weather, method)
    assert result.site_id == model.site_config.site_name
    assert result.panel_id is None
    assert result.forecast_horizon_hours == hours
    assert result.method == method
    assert [p.timestamp for p in result.points] == [h.time for h in weather.hourly]
    assert all(p.method == method for p in result.points)
    actual = np.array(
        [[p.energy_wh, p.power_w, p.confidence_lower, p.confidence_upper] for p in result.points]
    ).reshape(-1, 4)
    # Matrix vs single-row BLAS products can differ in their last few bits.
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-9)
    if hours >= 24 and method == ForecastMethod.STATISTICAL:
        assert np.count_nonzero(actual[:, 0] == 0) > 0  # Negative predictions stay clipped.
    assert predict.call_count == (1 if hours else 0)


@pytest.mark.parametrize("method", list(ForecastMethod))
@pytest.mark.parametrize("hours", [0, 48])
def test_unfitted_forecast_preserves_physical_fallback(hours, method):
    model = ForecastModel(create_test_site(), panel_id="test-1")
    weather = weather_for_hours(hours)
    expected = per_hour_reference(model, weather, method)
    with patch.object(model.statistical, "predict", side_effect=AssertionError("unfitted")):
        result = model.forecast(weather, method)
    assert result.panel_id == "test-1"
    assert result.forecast_horizon_hours == hours
    assert result.method == method
    actual = np.array(
        [[p.energy_wh, p.power_w, p.confidence_lower, p.confidence_upper] for p in result.points]
    ).reshape(-1, 4)
    np.testing.assert_array_equal(actual, expected)
