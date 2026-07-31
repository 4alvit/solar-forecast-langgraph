"""CLI entry point for solar forecasting."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from solar_forecast import (
    SiteConfig,
    DEFAULT_SITE,
    run_forecast,
)


def load_site_config(config_path: str | None) -> SiteConfig:
    """Load site configuration from file or use default."""
    if config_path:
        import importlib.util

        spec = importlib.util.spec_from_file_location("site_config", config_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load config from {config_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "SITE_CONFIG"):
            return module.SITE_CONFIG
        raise ValueError(f"SITE_CONFIG not found in {config_path}")
    return DEFAULT_SITE


async def main_async(
    site_config: SiteConfig,
    panel_id: str | None,
    horizon_hours: int,
    lookback_days: int,
    output_path: str | None,
    output_format: str,
):
    """Async main function."""
    print(f"Starting forecast for {site_config.site_name}...")
    if panel_id:
        panel = site_config.panel_by_id(panel_id)
        if panel:
            print(f"Panel: {panel.name} ({panel_id})")
        else:
            print(f"Warning: Panel {panel_id} not found, using first panel")

    state = await run_forecast(
        site_config=site_config,
        panel_id=panel_id,
        forecast_horizon_hours=horizon_hours,
        lookback_days=lookback_days,
    )

    if state.errors:
        print("Errors:", file=sys.stderr)
        for err in state.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if state.warnings:
        print("Warnings:")
        for warn in state.warnings:
            print(f"  - {warn}")

    forecast = state.final_forecast
    if forecast is None:
        print("Error: No forecast generated", file=sys.stderr)
        return 1

    print("\nForecast Summary:")
    print(f"  Site: {forecast.site_id}")
    print(f"  Panel: {forecast.panel_id or 'all'}")
    print(f"  Method: {forecast.method.value}")
    print(f"  Horizon: {forecast.forecast_horizon_hours} hours")
    print(f"  Total Energy: {forecast.total_energy_wh():.0f} Wh")
    print(f"  Generated: {forecast.generated_at.isoformat()}")

    # Print first few points
    print("\nNext 12 hours:")
    for p in forecast.points[:12]:
        print(
            f"  {p.timestamp.strftime('%Y-%m-%d %H:%M')}: "
            f"{p.power_w:.0f}W ({p.energy_wh:.0f}Wh) "
            f"[{p.confidence_lower:.0f}-{p.confidence_upper:.0f}]"
        )

    # Save output
    if output_path:
        out_data = forecast.model_dump(mode="json")
        out_data["generated_at"] = forecast.generated_at.isoformat()
        for p in out_data["points"]:
            p["timestamp"] = p["timestamp"]

        if output_format == "json":
            with open(output_path, "w") as f:
                json.dump(out_data, f, indent=2, default=str)
        elif output_format == "csv":
            import pandas as pd
            df = pd.DataFrame(out_data["points"])
            df.to_csv(output_path, index=False)
        print(f"\nOutput saved to {output_path}")

    return 0


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Solar Forecast LangGraph")
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        help="Path to site config Python file (must define SITE_CONFIG)",
    )
    parser.add_argument(
        "--panel",
        "-p",
        type=str,
        help="Panel ID to forecast (default: first panel)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=48,
        help="Forecast horizon in hours (default: 48)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=30,
        help="Historical lookback in days (default: 30)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="solar-forecast-langgraph 0.1.0",
    )

    args = parser.parse_args()

    try:
        site_config = load_site_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        return 1

    return asyncio.run(
        main_async(
            site_config=site_config,
            panel_id=args.panel,
            horizon_hours=args.horizon,
            lookback_days=args.lookback,
            output_path=args.output,
            output_format=args.format,
        )
    )


if __name__ == "__main__":
    sys.exit(main())