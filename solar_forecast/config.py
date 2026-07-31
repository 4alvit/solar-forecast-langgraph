"""Panel configuration schema for solar forecasting."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PanelConfig(BaseModel):
    """Configuration for a solar panel array."""

    model_config = {"extra": "forbid"}

    # Panel identification
    name: str = Field(..., description="Human-readable name for this panel array")
    panel_id: str = Field(..., description="Unique identifier")

    # Physical orientation
    azimuth: float = Field(
        ...,
        ge=0,
        le=360,
        description="Azimuth angle in degrees (0=North, 90=East, 180=South, 270=West)",
    )
    tilt: float = Field(
        ...,
        ge=0,
        le=90,
        description="Tilt angle in degrees from horizontal (0=flat, 90=vertical)",
    )

    # Electrical characteristics
    capacity_kw: float = Field(..., gt=0, description="Rated capacity in kW (DC)")
    module_count: int = Field(..., ge=1, description="Number of modules in array")
    module_efficiency: float = Field(
        default=0.20, ge=0.1, le=0.3, description="Module efficiency (fraction)"
    )
    temperature_coefficient: float = Field(
        default=-0.0035, le=0, description="Power temperature coefficient (%/°C)"
    )

    # Inverter parameters
    inverter_efficiency: float = Field(
        default=0.96, ge=0.85, le=0.99, description="Inverter efficiency (fraction)"
    )
    dc_ac_ratio: float = Field(
        default=1.2, ge=0.8, le=2.0, description="DC/AC ratio (oversizing factor)"
    )

    # Location (for sun position calculations)
    latitude: float = Field(..., ge=-90, le=90, description="Site latitude in degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Site longitude in degrees")
    timezone: str = Field(default="UTC", description="IANA timezone identifier")

    # Losses
    shading_loss: float = Field(
        default=0.0, ge=0, le=1, description="Shading loss factor (fraction)"
    )
    soiling_loss: float = Field(
        default=0.02, ge=0, le=0.1, description="Soiling loss factor (fraction)"
    )
    wiring_loss: float = Field(
        default=0.01, ge=0, le=0.05, description="AC/DC wiring loss factor (fraction)"
    )

    def effective_capacity_kw(self) -> float:
        """Calculate effective AC capacity after losses."""
        dc_capacity = self.capacity_kw
        ac_capacity = dc_capacity * self.inverter_efficiency
        total_loss = (
            1 - self.shading_loss
        ) * (
            1 - self.soiling_loss
        ) * (
            1 - self.wiring_loss
        )
        return ac_capacity * total_loss


class SiteConfig(BaseModel):
    """Complete site configuration with multiple panel arrays."""

    model_config = {"extra": "forbid"}

    site_name: str = Field(..., description="Site identifier")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    timezone: str = Field(default="UTC")
    elevation_m: float = Field(default=0, ge=-500, le=5000)
    panels: list[PanelConfig] = Field(..., min_length=1)

    def total_capacity_kw(self) -> float:
        """Total effective AC capacity of all panels."""
        return sum(p.effective_capacity_kw() for p in self.panels)

    def panel_by_id(self, panel_id: str) -> PanelConfig | None:
        """Find panel by ID."""
        for p in self.panels:
            if p.panel_id == panel_id:
                return p
        return None


# Default configuration for Victron system (example)
DEFAULT_SITE = SiteConfig(
    site_name="victron-site",
    latitude=52.37,
    longitude=4.90,
    timezone="Europe/Amsterdam",
    elevation_m=0,
    panels=[
        PanelConfig(
            name="South Roof",
            panel_id="south-roof",
            azimuth=180,
            tilt=35,
            capacity_kw=5.0,
            module_count=14,
            latitude=52.37,
            longitude=4.90,
        ),
        PanelConfig(
            name="West Roof",
            panel_id="west-roof",
            azimuth=270,
            tilt=30,
            capacity_kw=3.0,
            module_count=8,
            latitude=52.37,
            longitude=4.90,
        ),
    ],
)