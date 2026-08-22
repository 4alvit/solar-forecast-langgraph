"""Forecast model: statistical baseline + LLM reasoning."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler

from solar_forecast.config import PanelConfig, SiteConfig
from solar_forecast.weather import WeatherForecast


class ForecastMethod(str, Enum):
    """Forecast method used."""

    STATISTICAL = "statistical"
    PHYSICAL = "physical"
    LLM_ENHANCED = "llm_enhanced"
    ENSEMBLE = "ensemble"


class ForecastPoint(BaseModel):
    """Single forecast point."""

    model_config = {"extra": "forbid"}

    timestamp: datetime = Field(..., description="UTC timestamp")
    energy_wh: float = Field(..., ge=0, description="Predicted energy (Wh)")
    power_w: float = Field(..., ge=0, description="Predicted power (W)")
    confidence_lower: float = Field(..., ge=0, description="Lower confidence bound (Wh)")
    confidence_upper: float = Field(..., ge=0, description="Upper confidence bound (Wh)")
    method: ForecastMethod = Field(..., description="Method used")


class GenerationForecast(BaseModel):
    """Complete generation forecast for a site/panel."""

    model_config = {"extra": "forbid", "protected_namespaces": ()}

    site_id: str
    panel_id: str | None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    forecast_horizon_hours: int
    points: list[ForecastPoint]
    method: ForecastMethod
    model_version: str = "0.1.0"

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to pandas DataFrame."""
        return pd.DataFrame([p.model_dump() for p in self.points])

    def total_energy_wh(self) -> float:
        """Total predicted energy over forecast horizon."""
        return sum(p.energy_wh for p in self.points)


@dataclass
class SolarPosition:
    """Calculated solar position."""

    zenith: float  # degrees from vertical
    azimuth: float  # degrees from North
    elevation: float  # degrees above horizon
    air_mass: float


class PhysicalModel:
    """Physical solar generation model (clear-sky + cloud adjustment)."""

    def __init__(self, panel: PanelConfig):
        self.panel = panel

    def calculate_solar_position(self, dt: datetime, lat: float, lon: float) -> SolarPosition:
        """Calculate solar position using SPA algorithm (simplified)."""
        # Simplified solar position calculation
        # For production, use pvlib.solarposition.get_solarposition
        day_of_year = dt.timetuple().tm_yday

        # Local solar time: convert to UTC, then shift by longitude (15 deg/h).
        # Forecast timestamps may carry any timezone (site default is UTC), so
        # derive solar time from absolute time instead of the wall clock.
        # ponytail: no equation-of-time correction (+-16 min), add if it matters.
        utc_dt = dt.astimezone(UTC) if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        hour = utc_dt.hour + utc_dt.minute / 60 + utc_dt.second / 3600 + lon / 15.0

        # Solar declination (radians)
        decl = -23.44 * np.cos(2 * np.pi * (day_of_year + 10) / 365) * np.pi / 180

        # Hour angle (radians)
        hour_angle = (hour - 12) * 15 * np.pi / 180

        lat_rad = lat * np.pi / 180

        # Solar elevation
        sin_elev = np.sin(lat_rad) * np.sin(decl) + np.cos(lat_rad) * np.cos(decl) * np.cos(
            hour_angle
        )
        elevation = np.arcsin(np.clip(sin_elev, -1, 1)) * 180 / np.pi

        # Solar azimuth
        cos_az = (np.sin(decl) - np.sin(lat_rad) * sin_elev) / (
            np.cos(lat_rad) * np.cos(np.arcsin(sin_elev))
        )
        azimuth = np.arccos(np.clip(cos_az, -1, 1)) * 180 / np.pi
        if hour_angle > 0:
            azimuth = 360 - azimuth

        zenith = 90 - elevation

        # Air mass (Kasten-Young 1989)
        if elevation > 0:
            air_mass = 1 / (
                np.sin(elevation * np.pi / 180) + 0.50572 * (elevation + 6.07995) ** -1.6364
            )
        else:
            air_mass = 0

        return SolarPosition(zenith=zenith, azimuth=azimuth, elevation=elevation, air_mass=air_mass)

    def calculate_poa_irradiance(
        self, solar_pos: SolarPosition, ghi: float, dni: float, dhi: float
    ) -> float:
        """Calculate plane-of-array irradiance using Hay-Davies model."""
        if solar_pos.elevation <= 0:
            return 0.0

        # Angle of incidence
        tilt_rad = self.panel.tilt * np.pi / 180
        azimuth_diff = (solar_pos.azimuth - self.panel.azimuth) * np.pi / 180
        zenith_rad = solar_pos.zenith * np.pi / 180

        cos_aoi = np.cos(zenith_rad) * np.cos(tilt_rad) + np.sin(zenith_rad) * np.sin(
            tilt_rad
        ) * np.cos(azimuth_diff)
        cos_aoi = max(0, cos_aoi)

        # Beam component
        if dni > 0 and np.cos(zenith_rad) > 0:
            beam = dni * cos_aoi / np.cos(zenith_rad)
        else:
            beam = 0

        # Diffuse component (Hay-Davies)
        rb = beam / dni if dni > 0 else 0
        diffuse_sky = dhi * (1 - rb) * (1 + np.cos(tilt_rad)) / 2
        diffuse_ground = ghi * 0.2 * (1 - np.cos(tilt_rad)) / 2  # albedo=0.2

        poa = beam + diffuse_sky + diffuse_ground
        return max(0, poa)

    def predict_clear_sky(self, solar_pos: SolarPosition, poa: float) -> float:
        """Predict power under clear sky conditions."""
        if solar_pos.elevation <= 0:
            return 0.0

        # Simplified: linear with POA, temperature derating
        temp_derating = 1 + self.panel.temperature_coefficient * (25 - 20)  # assume 20°C
        dc_power = self.panel.capacity_kw * 1000 * (poa / 1000) * temp_derating
        ac_power = min(
            dc_power * self.panel.inverter_efficiency,
            self.panel.capacity_kw * 1000 / self.panel.dc_ac_ratio,
        )
        return max(0, ac_power)

    def apply_cloud_adjustment(
        self, clear_power: float, cloud_cover: float, cloud_type: str = "total"
    ) -> float:
        """Adjust clear-sky power for cloud cover."""
        # Empirical cloud adjustment
        # Total cloud cover 0-100%
        cc = cloud_cover / 100

        # Different cloud types have different impacts
        if cloud_type == "low":
            # Low clouds block more
            factor = 1 - 0.85 * cc
        elif cloud_type == "high":
            # High clouds (cirrus) less blocking
            factor = 1 - 0.4 * cc
        else:
            # Total cloud cover
            factor = 1 - 0.75 * cc

        return clear_power * max(0.05, factor)  # minimum 5% (diffuse)


class StatisticalModel:
    """Statistical baseline model using historical data."""

    def __init__(self):
        self.scaler = StandardScaler()
        self.model: LinearRegression | None = None
        self.feature_names: list[str] = []
        self.is_fitted = False

    def prepare_features(
        self,
        weather: WeatherForecast,
        historical: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Prepare features for statistical model."""
        rows = []
        for h in weather.hourly:
            dt = h.time
            row = {
                "hour": dt.hour,
                "month": dt.month,
                "day_of_year": dt.timetuple().tm_yday,
                "weekday": dt.weekday(),
                "temperature": h.temperature_2m,
                "humidity": h.relative_humidity_2m,
                "cloud_cover": h.cloud_cover,
                "cloud_cover_low": h.cloud_cover_low,
                "cloud_cover_mid": h.cloud_cover_mid,
                "cloud_cover_high": h.cloud_cover_high,
                "ghi": h.shortwave_radiation,
                "dni": h.direct_radiation,
                "dhi": h.diffuse_radiation,
                "wind_speed": h.wind_speed_10m,
                "pressure": h.pressure_msl,
            }
            rows.append(row)
        return pd.DataFrame(rows)

    def fit(self, weather: WeatherForecast, generation: pd.DataFrame) -> StatisticalModel:
        """Fit statistical model on historical data."""
        # Align weather and generation by timestamp
        weather_df = self.prepare_features(weather)
        weather_df["timestamp"] = [h.time for h in weather.hourly]
        weather_df.set_index("timestamp", inplace=True)

        # Merge with generation
        merged = weather_df.join(generation["energy_wh"], how="inner")
        merged = merged.dropna()

        if len(merged) < 24:
            raise ValueError("Insufficient training data (need at least 24 hours)")

        # Feature selection
        feature_cols = [c for c in merged.columns if c != "energy_wh"]
        self.feature_names = feature_cols

        X = merged[feature_cols].values
        y = merged["energy_wh"].values

        # Scale features
        X_scaled = self.scaler.fit_transform(X)

        # Fit linear regression
        self.model = LinearRegression()
        self.model.fit(X_scaled, y)

        self.is_fitted = True
        return self

    def predict(self, weather: WeatherForecast) -> np.ndarray:
        """Predict generation for weather forecast."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")

        X = self.prepare_features(weather)
        X_scaled = self.scaler.transform(X[self.feature_names].values)
        predictions = self.model.predict(X_scaled)
        return np.maximum(predictions, 0)  # Clip negative predictions


class ForecastModel:
    """Ensemble forecast model combining physical, statistical, and LLM."""

    def __init__(
        self,
        site_config: SiteConfig,
        panel_id: str | None = None,
    ):
        self.site_config = site_config
        self.panel = site_config.panel_by_id(panel_id) if panel_id else site_config.panels[0]
        self.physical = PhysicalModel(self.panel)
        self.statistical = StatisticalModel()
        self.panel_id = panel_id

    def train(self, weather: WeatherForecast, historical: pd.DataFrame) -> ForecastModel:
        """Train statistical component on historical data."""
        self.statistical.fit(weather, historical)
        return self

    def forecast(
        self,
        weather: WeatherForecast,
        method: ForecastMethod = ForecastMethod.ENSEMBLE,
    ) -> GenerationForecast:
        """Generate forecast using specified method."""
        points = []

        for i, h in enumerate(weather.hourly):
            # Physical model
            solar_pos = self.physical.calculate_solar_position(
                h.time, self.site_config.latitude, self.site_config.longitude
            )
            poa = self.physical.calculate_poa_irradiance(
                solar_pos, h.shortwave_radiation, h.direct_radiation, h.diffuse_radiation
            )
            clear_power = self.physical.predict_clear_sky(solar_pos, poa)
            physical_power = self.physical.apply_cloud_adjustment(clear_power, h.cloud_cover)

            # Statistical model (if fitted)
            if self.statistical.is_fitted:
                stat_pred = self.statistical.predict(
                    WeatherForecast(
                        latitude=weather.latitude,
                        longitude=weather.longitude,
                        elevation=weather.elevation,
                        timezone=weather.timezone,
                        hourly=[h],
                    )
                )[0]
            else:
                stat_pred = physical_power

            # Ensemble: weighted average
            if method == ForecastMethod.ENSEMBLE:
                pred_power = 0.6 * physical_power + 0.4 * stat_pred
            elif method == ForecastMethod.PHYSICAL:
                pred_power = physical_power
            elif method == ForecastMethod.STATISTICAL:
                pred_power = stat_pred
            else:
                pred_power = physical_power  # LLM enhanced handled separately

            pred_energy = pred_power * 1.0  # 1 hour interval

            # Confidence intervals (simple heuristic)
            uncertainty = 0.2 * pred_energy  # 20% uncertainty
            points.append(
                ForecastPoint(
                    timestamp=h.time,
                    energy_wh=max(0, pred_energy),
                    power_w=max(0, pred_power),
                    confidence_lower=max(0, pred_energy - uncertainty),
                    confidence_upper=pred_energy + uncertainty,
                    method=method,
                )
            )

        return GenerationForecast(
            site_id=self.site_config.site_name,
            panel_id=self.panel_id,
            forecast_horizon_hours=len(points),
            points=points,
            method=method,
        )


async def enhance_with_llm(
    base_forecast: GenerationForecast,
    weather: WeatherForecast,
    site_config: SiteConfig,
    panel_config: PanelConfig,
    recent_actuals: pd.DataFrame | None = None,
) -> GenerationForecast:
    """Enhance forecast with LLM reasoning using OpenAI API.

    Analyzes weather patterns, forecast data, and historical actuals to make
    intelligent adjustments to the forecast.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        # No API key configured - return base forecast with original method
        # This avoids the fake "LLM-enhanced" label
        return base_forecast

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError:
        return base_forecast

    # Prepare context for LLM
    context = _build_llm_context(base_forecast, weather, site_config, panel_config, recent_actuals)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=api_key)

    system_prompt = """You are a solar forecasting expert. Analyze the provided weather forecast,
    solar panel configuration, and historical generation data to refine the base forecast.

    Provide adjustments as JSON with these optional fields:
    - "power_adjustment_pct": percentage adjustment to power predictions (-30 to +30)
    - "confidence_multiplier": multiplier for confidence intervals (0.5 to 2.0)
    - "flags": list of warning flags for anomalous conditions
    - "reasoning": brief explanation of your adjustments

    Be conservative. Only make adjustments when you have clear reasoning from the data."""

    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=context),
        ]
    )

    import json

    try:
        adjustment = json.loads(response.content)
    except json.JSONDecodeError:
        return base_forecast

    # Apply adjustments
    power_adj = adjustment.get("power_adjustment_pct", 0) / 100
    conf_mult = adjustment.get("confidence_multiplier", 1.0)
    flags = adjustment.get("flags", [])

    enhanced_points = []
    for p in base_forecast.points:
        adj_power = max(0, p.power_w * (1 + power_adj))
        adj_energy = max(0, p.energy_wh * (1 + power_adj))
        uncertainty = p.confidence_upper - p.energy_wh
        new_uncertainty = uncertainty * conf_mult

        enhanced_points.append(
            ForecastPoint(
                timestamp=p.timestamp,
                energy_wh=adj_energy,
                power_w=adj_power,
                confidence_lower=max(0, adj_energy - new_uncertainty),
                confidence_upper=adj_energy + new_uncertainty,
                method=ForecastMethod.LLM_ENHANCED,
            )
        )

    # Update model version with LLM indicator
    model_version = base_forecast.model_version
    if not model_version.endswith("+llm"):
        model_version = model_version + "+llm"

    return GenerationForecast(
        site_id=base_forecast.site_id,
        panel_id=base_forecast.panel_id,
        generated_at=base_forecast.generated_at,
        forecast_horizon_hours=base_forecast.forecast_horizon_hours,
        points=enhanced_points,
        method=ForecastMethod.LLM_ENHANCED,
        model_version=model_version,
    )


def _build_llm_context(
    base_forecast: GenerationForecast,
    weather: WeatherForecast,
    site_config: SiteConfig,
    panel_config: PanelConfig,
    recent_actuals: pd.DataFrame | None = None,
) -> str:
    """Build context string for LLM analysis."""
    import json

    # Summarize base forecast
    total_energy = base_forecast.total_energy_wh()
    avg_power = sum(p.power_w for p in base_forecast.points) / len(base_forecast.points)

    # Summarize weather
    hourly_summary = []
    for h in weather.hourly:
        hourly_summary.append(
            {
                "time": h.time.isoformat(),
                "ghi": h.shortwave_radiation,
                "cloud_cover": h.cloud_cover,
                "cloud_low": h.cloud_cover_low,
                "cloud_mid": h.cloud_cover_mid,
                "cloud_high": h.cloud_cover_high,
                "temp": h.temperature_2m,
                "humidity": h.relative_humidity_2m,
            }
        )

    # Historical comparison if available
    hist_summary = {}
    if (
        recent_actuals is not None
        and not recent_actuals.empty
        and "energy_wh" in recent_actuals.columns
    ):
        hist_summary = {
            "mean_actual_wh": float(recent_actuals["energy_wh"].mean()),
            "max_actual_wh": float(recent_actuals["energy_wh"].max()),
            "count": len(recent_actuals),
        }

    context = {
        "site": site_config.site_name,
        "panel": {
            "id": panel_config.panel_id,
            "capacity_kw": panel_config.capacity_kw,
            "azimuth": panel_config.azimuth,
            "tilt": panel_config.tilt,
        },
        "base_forecast": {
            "method": base_forecast.method.value,
            "total_energy_wh": total_energy,
            "avg_power_w": avg_power,
            "hours": len(base_forecast.points),
        },
        "weather_forecast": hourly_summary,
        "historical_actuals": hist_summary,
    }

    return json.dumps(context, indent=2)
