"""Historical generation data loader from inverter-monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field


class GenerationRecord(BaseModel):
    """Single generation data point from inverter monitoring."""

    model_config = {"extra": "forbid"}

    timestamp: datetime = Field(..., description="UTC timestamp")
    site_id: str = Field(..., description="Site identifier")
    panel_id: str | None = Field(None, description="Panel array identifier")
    energy_wh: float = Field(..., ge=0, description="Energy generated in Wh")
    power_w: float | None = Field(None, ge=0, description="Instantaneous power in W")
    voltage_v: float | None = Field(None, description="DC voltage")
    current_a: float | None = Field(None, description="DC current")


class HistoricalData(BaseModel):
    """Container for historical generation data."""

    model_config = {"extra": "forbid"}

    site_id: str
    panel_id: str | None
    records: list[GenerationRecord]
    start_date: datetime
    end_date: datetime
    interval_minutes: int = Field(default=15, description="Data resolution in minutes")

    def to_dataframe(self) -> pd.DataFrame:
        """Convert to pandas DataFrame with datetime index."""
        if not self.records:
            return pd.DataFrame()

        df = pd.DataFrame([r.model_dump() for r in self.records])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def resample(self, freq: str) -> HistoricalData:
        """Resample data to different frequency."""
        df = self.to_dataframe()
        if df.empty:
            return self

        resampled = (
            df.resample(freq)
            .agg(
                {
                    "energy_wh": "sum",
                    "power_w": "mean",
                    "voltage_v": "mean",
                    "current_a": "mean",
                    "site_id": "first",
                    "panel_id": "first",
                }
            )
            .dropna(subset=["energy_wh"])
        )

        records = []
        for idx, row in resampled.iterrows():
            records.append(
                GenerationRecord(
                    timestamp=idx.to_pydatetime(),
                    site_id=row["site_id"],
                    panel_id=row["panel_id"],
                    energy_wh=row["energy_wh"],
                    power_w=row["power_w"] if pd.notna(row["power_w"]) else None,
                    voltage_v=row["voltage_v"] if pd.notna(row["voltage_v"]) else None,
                    current_a=row["current_a"] if pd.notna(row["current_a"]) else None,
                )
            )

        return HistoricalData(
            site_id=self.site_id,
            panel_id=self.panel_id,
            records=records,
            start_date=records[0].timestamp if records else self.start_date,
            end_date=records[-1].timestamp if records else self.end_date,
            interval_minutes=int(pd.Timedelta(freq).total_seconds() / 60),
        )


@dataclass
class InverterMonitoringLoader:
    """Load historical generation data from inverter-monitoring webhook."""

    base_url: str = "http://localhost:8080"  # inverter-monitoring webhook
    api_key: str | None = None
    timeout: float = 30.0

    async def fetch_generation(
        self,
        site_id: str,
        start: datetime,
        end: datetime,
        panel_id: str | None = None,
    ) -> HistoricalData:
        """Fetch generation data from inverter-monitoring API.

        Args:
            site_id: Site identifier
            start: Start time (UTC)
            end: End time (UTC)
            panel_id: Optional panel array filter

        Returns:
            HistoricalData container
        """
        import httpx

        params = {
            "site_id": site_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        if panel_id:
            params["panel_id"] = panel_id

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/generation", params=params, headers=headers
            )
            response.raise_for_status()
            data = response.json()

        return self._parse_response(data, site_id, panel_id, start, end)

    def _parse_response(
        self,
        data: dict[str, Any],
        site_id: str,
        panel_id: str | None,
        start: datetime,
        end: datetime,
    ) -> HistoricalData:
        """Parse API response into HistoricalData."""
        records = []
        for item in data.get("records", []):
            records.append(
                GenerationRecord(
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    site_id=item["site_id"],
                    panel_id=item.get("panel_id"),
                    energy_wh=item["energy_wh"],
                    power_w=item.get("power_w"),
                    voltage_v=item.get("voltage_v"),
                    current_a=item.get("current_a"),
                )
            )

        if not records:
            return HistoricalData(
                site_id=site_id,
                panel_id=panel_id,
                records=[],
                start_date=start,
                end_date=end,
            )

        records.sort(key=lambda r: r.timestamp)
        return HistoricalData(
            site_id=site_id,
            panel_id=panel_id,
            records=records,
            start_date=records[0].timestamp,
            end_date=records[-1].timestamp,
            interval_minutes=data.get("interval_minutes", 15),
        )

    async def fetch_recent_days(
        self, site_id: str, days: int = 30, panel_id: str | None = None
    ) -> HistoricalData:
        """Fetch recent generation data."""
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        return await self.fetch_generation(site_id, start, end, panel_id)


class LocalCSVLoader:
    """Load historical data from local CSV files (fallback)."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def load_site_data(
        self, site_id: str, panel_id: str | None = None, days: int = 365
    ) -> HistoricalData:
        """Load generation data from local CSV files."""
        csv_path = self.data_dir / f"{site_id}_generation.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"No data file: {csv_path}")

        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        if panel_id and "panel_id" in df.columns:
            df = df[df["panel_id"] == panel_id]

        # Filter by date range
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]

        records = []
        for _, row in df.iterrows():
            records.append(
                GenerationRecord(
                    timestamp=row["timestamp"].to_pydatetime(),
                    site_id=row["site_id"],
                    panel_id=row.get("panel_id"),
                    energy_wh=row["energy_wh"],
                    power_w=row.get("power_w"),
                    voltage_v=row.get("voltage_v"),
                    current_a=row.get("current_a"),
                )
            )

        records.sort(key=lambda r: r.timestamp)
        if not records:
            return HistoricalData(
                site_id=site_id,
                panel_id=panel_id,
                records=[],
                start_date=start,
                end_date=end,
            )

        return HistoricalData(
            site_id=site_id,
            panel_id=panel_id,
            records=records,
            start_date=records[0].timestamp,
            end_date=records[-1].timestamp,
            interval_minutes=15,
        )
