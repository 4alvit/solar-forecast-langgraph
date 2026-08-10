"""Tests for weather module."""

from datetime import UTC, datetime

import pytest

from solar_forecast.weather import OpenMeteoClient, WeatherForecast, WeatherHourly


def test_weather_hourly():
    dt = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
    hourly = WeatherHourly(
        time=dt,
        temperature_2m=20.5,
        relative_humidity_2m=65,
        cloud_cover=30,
        cloud_cover_low=10,
        cloud_cover_mid=15,
        cloud_cover_high=5,
        shortwave_radiation=800,
        direct_radiation=600,
        diffuse_radiation=200,
        wind_speed_10m=3.5,
        wind_direction_10m=180,
        pressure_msl=1013.25,
    )
    assert hourly.time == dt
    assert hourly.temperature_2m == 20.5
    assert hourly.cloud_cover == 30


def test_weather_forecast_to_dataframe():
    dt = datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
    hourly = WeatherHourly(
        time=dt,
        temperature_2m=20.5,
        relative_humidity_2m=65,
        cloud_cover=30,
        cloud_cover_low=10,
        cloud_cover_mid=15,
        cloud_cover_high=5,
        shortwave_radiation=800,
        direct_radiation=600,
        diffuse_radiation=200,
        wind_speed_10m=3.5,
        wind_direction_10m=180,
        pressure_msl=1013.25,
    )
    forecast = WeatherForecast(
        latitude=52.37,
        longitude=4.90,
        elevation=0,
        timezone="UTC",
        hourly=[hourly],
    )
    rows = forecast.to_dataframe_rows()
    assert len(rows) == 1
    assert rows[0]["temperature_2m"] == 20.5


@pytest.mark.asyncio
async def test_openmeteo_client_parse_response():
    """Test the response parsing logic directly."""
    client = OpenMeteoClient()

    mock_response = {
        "latitude": 52.37,
        "longitude": 4.90,
        "elevation": 0,
        "timezone": "UTC",
        "hourly": {
            "time": ["2024-01-15T12:00:00Z"],
            "temperature_2m": [20.0],
            "relative_humidity_2m": [60],
            "cloud_cover": [20],
            "cloud_cover_low": [5],
            "cloud_cover_mid": [10],
            "cloud_cover_high": [5],
            "shortwave_radiation": [800],
            "direct_radiation": [600],
            "diffuse_radiation": [200],
            "wind_speed_10m": [3.0],
            "wind_direction_10m": [180],
            "pressure_msl": [1013.25],
        },
    }

    forecast = client._parse_response(mock_response)

    assert isinstance(forecast, WeatherForecast)
    assert len(forecast.hourly) == 1
    assert forecast.hourly[0].temperature_2m == 20.0
    assert forecast.hourly[0].shortwave_radiation == 800
    assert forecast.hourly[0].cloud_cover == 20
