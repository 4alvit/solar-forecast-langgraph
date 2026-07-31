# Example site configuration for solar-forecast-langgraph
# Copy to site_config.local.py and fill in your values

from solar_forecast.config import PanelConfig, SiteConfig

# Your site configuration
SITE_CONFIG = SiteConfig(
    site_name="my-solar-site",
    latitude=52.37,      # Your latitude
    longitude=4.90,      # Your longitude
    timezone="Europe/Amsterdam",
    elevation_m=0,
    panels=[
        PanelConfig(
            name="South Roof",
            panel_id="south-roof",
            azimuth=180,      # South-facing
            tilt=35,          # 35 degree tilt
            capacity_kw=5.0,  # 5kW DC
            module_count=14,
            latitude=52.37,
            longitude=4.90,
        ),
        PanelConfig(
            name="West Roof",
            panel_id="west-roof",
            azimuth=270,      # West-facing
            tilt=30,          # 30 degree tilt
            capacity_kw=3.0,  # 3kW DC
            module_count=8,
            latitude=52.37,
            longitude=4.90,
        ),
    ],
)

# For inverter-monitoring integration (optional)
INVERTER_MONITORING_URL = "http://localhost:8080"  # Your inverter-monitoring webhook
INVERTER_MONITORING_API_KEY = "your_api_key_here"   # Optional API key

# For inverter-control integration (optional)
INVERTER_CONTROL_URL = "http://localhost:8081"      # Your inverter-control API
INVERTER_CONTROL_API_KEY = "your_api_key_here"      # Optional API key

# LLM settings (optional, for future LLM enhancement)
OPENAI_API_KEY = "your_openai_key_here"  # For LLM-enhanced forecasting
LLM_MODEL = "gpt-4o-mini"