"""Weather data agent using OpenMeteo API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential

OPENMETEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"


class WeatherHourly(BaseModel):
    """Hourly weather data point."""

    model_config = {"extra": "forbid"}

    time: datetime = Field(..., description="Timestamp in UTC")
    temperature_2m: float = Field(..., description="Air temperature at 2m (°C)")
    relative_humidity_2m: float = Field(..., description="Relative humidity at 2m (%)")
    cloud_cover: float = Field(..., description="Total cloud cover (%)")
    cloud_cover_low: float = Field(..., description="Low cloud cover (%)")
    cloud_cover_mid: float = Field(..., description="Mid cloud cover (%)")
    cloud_cover_high: float = Field(..., description="High cloud cover (%)")
    shortwave_radiation: float = Field(..., description="Global horizontal irradiance (W/m²)")
    direct_radiation: float = Field(..., description="Direct normal irradiance (W/m²)")
    diffuse_radiation: float = Field(..., description="Diffuse horizontal irradiance (W/m²)")
    wind_speed_10m: float = Field(..., description="Wind speed at 10m (m/s)")
    wind_direction_10m: float = Field(..., description="Wind direction at 10m (°)")
    pressure_msl: float = Field(..., description="Mean sea level pressure (hPa)")


class WeatherForecast(BaseModel):
    """Complete weather forecast for a location."""

    model_config = {"extra": "forbid"}

    latitude: float
    longitude: float
    elevation: float
    timezone: str
    hourly: list[WeatherHourly]

    def to_dataframe_rows(self) -> list[dict[str, Any]]:
        """Convert to list of dicts for DataFrame creation."""
        return [h.model_dump() for h in self.hourly]


@dataclass
class OpenMeteoClient:
    """Async client for OpenMeteo API with retry logic."""

    base_url: str = OPENMETEO_BASE_URL
    timeout: float = 30.0
    max_retries: int = 3

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
    )
    async def fetch_forecast(
        self,
        latitude: float,
        longitude: float,
        horizon_hours: int = 168,
        timezone: str = "UTC",
        past_days: int = 0,
    ) -> WeatherForecast:
        """Fetch weather forecast for location.

        Args:
            latitude: Site latitude
            longitude: Site longitude
            horizon_hours: Forecast horizon in hours (max 168 for free tier)
            timezone: IANA timezone for response times
            past_days: Days of historical weather to prepend (0-92), used to
                train the statistical model against past generation data

        Returns:
            WeatherForecast with hourly data

        Raises:
            httpx.HTTPError: On API error after retries
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(
                f"{h}"
                for h in [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "cloud_cover",
                    "cloud_cover_low",
                    "cloud_cover_mid",
                    "cloud_cover_high",
                    "shortwave_radiation",
                    "direct_radiation",
                    "diffuse_radiation",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "pressure_msl",
                ]
            ),
            "forecast_hours": min(horizon_hours, 168),
            # past_days replaces past_hours when set (past_hours maxes at 48)
            **({"past_days": past_days} if past_days > 0 else {"past_hours": 1}),
            "timezone": timezone,
            "models": "best_match",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict[str, Any]) -> WeatherForecast:
        """Parse OpenMeteo JSON response into WeatherForecast."""
        hourly_data = data.get("hourly", {})
        times = hourly_data.get("time", [])

        # OpenMeteo returns naive timestamps in the requested timezone;
        # attach it so downstream comparisons with UTC-aware datetimes work
        tz = ZoneInfo(data.get("timezone", "UTC"))

        hourly = []
        for i, t_str in enumerate(times):
            dt = datetime.fromisoformat(t_str).replace(tzinfo=tz)
            hourly.append(
                WeatherHourly(
                    time=dt,
                    temperature_2m=hourly_data["temperature_2m"][i],
                    relative_humidity_2m=hourly_data["relative_humidity_2m"][i],
                    cloud_cover=hourly_data["cloud_cover"][i],
                    cloud_cover_low=hourly_data["cloud_cover_low"][i],
                    cloud_cover_mid=hourly_data["cloud_cover_mid"][i],
                    cloud_cover_high=hourly_data["cloud_cover_high"][i],
                    shortwave_radiation=hourly_data["shortwave_radiation"][i],
                    direct_radiation=hourly_data["direct_radiation"][i],
                    diffuse_radiation=hourly_data["diffuse_radiation"][i],
                    wind_speed_10m=hourly_data["wind_speed_10m"][i],
                    wind_direction_10m=hourly_data["wind_direction_10m"][i],
                    pressure_msl=hourly_data["pressure_msl"][i],
                )
            )

        return WeatherForecast(
            latitude=data["latitude"],
            longitude=data["longitude"],
            elevation=data["elevation"],
            timezone=data["timezone"],
            hourly=hourly,
        )

    async def fetch_current(
        self, latitude: float, longitude: float, timezone: str = "UTC"
    ) -> WeatherHourly:
        """Fetch current weather conditions."""
        forecast = await self.fetch_forecast(
            latitude, longitude, horizon_hours=1, timezone=timezone
        )
        now = datetime.now(UTC)
        # Find closest hour
        closest = min(forecast.hourly, key=lambda h: abs((h.time - now).total_seconds()))
        return closest


async def main():
    """Test the weather client."""
    client = OpenMeteoClient()
    # Amsterdam coordinates
    forecast = await client.fetch_forecast(52.37, 4.90, horizon_hours=48)
    print(f"Fetched {len(forecast.hourly)} hourly forecasts")
    for h in forecast.hourly[:5]:
        print(f"  {h.time}: GHI={h.shortwave_radiation:.0f} W/m², Cloud={h.cloud_cover:.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
