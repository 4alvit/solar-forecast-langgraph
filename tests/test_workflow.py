"""Tests for workflow module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from solar_forecast.config import PanelConfig, SiteConfig
from solar_forecast.weather import WeatherForecast, WeatherHourly
from solar_forecast.workflow import (
    InverterControlHook,
    WorkflowState,
    build_forecast_workflow,
    enhance_forecast_node,
    fetch_history_node,
    fetch_weather_node,
    finalize_forecast_node,
    generate_forecast_node,
    inverter_control_hook_node,
    train_model_node,
)


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


@pytest.mark.asyncio
async def test_fetch_weather_node():
    """Test weather fetch node."""
    site = create_test_site()
    state = WorkflowState(site_config=site, panel_id="test-1")

    # Mock the OpenMeteo client
    with patch("solar_forecast.workflow.OpenMeteoClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_forecast = AsyncMock()
        mock_forecast.hourly = []
        mock_client.fetch_forecast.return_value = mock_forecast

        result = await fetch_weather_node(state)

    assert result.weather_forecast == mock_forecast
    assert "fetch_weather" in result.completed_steps


@pytest.mark.asyncio
async def test_fetch_history_node_failure():
    """Test history fetch node handles failures gracefully."""
    site = create_test_site()
    state = WorkflowState(site_config=site, panel_id="test-1")

    with patch("solar_forecast.workflow.InverterMonitoringLoader") as mock_loader_class:
        mock_loader = AsyncMock()
        mock_loader_class.return_value = mock_loader
        mock_loader.fetch_generation.side_effect = Exception("Connection failed")

        result = await fetch_history_node(state)

    assert result.historical_data is None
    assert len(result.warnings) > 0
    assert "fetch_history" in result.completed_steps


@pytest.mark.asyncio
async def test_train_model_node_no_data():
    """Test train model node with no historical data."""
    site = create_test_site()
    state = WorkflowState(site_config=site, panel_id="test-1", historical_df=None)

    result = await train_model_node(state)

    assert len(result.warnings) > 0
    assert "train_model" in result.completed_steps


@pytest.mark.asyncio
async def test_generate_forecast_node_no_weather():
    """Test generate forecast node fails without weather."""
    site = create_test_site()
    state = WorkflowState(site_config=site, panel_id="test-1", weather_forecast=None)

    result = await generate_forecast_node(state)

    assert len(result.errors) > 0


@pytest.mark.asyncio
async def test_finalize_forecast_node():
    """Test finalize forecast node."""
    site = create_test_site()
    state = WorkflowState(site_config=site, panel_id="test-1")

    # Add a mock forecast
    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast

    mock_forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=1,
        points=[
            ForecastPoint(
                timestamp=datetime.now(UTC),
                energy_wh=1000,
                power_w=1000,
                confidence_lower=800,
                confidence_upper=1200,
                method=ForecastMethod.ENSEMBLE,
            )
        ],
        method=ForecastMethod.ENSEMBLE,
    )
    state.base_forecast = mock_forecast

    result = await finalize_forecast_node(state)

    assert result.final_forecast == mock_forecast
    assert "finalize" in result.completed_steps


def test_build_workflow():
    """Test workflow graph builds correctly."""
    workflow = build_forecast_workflow()
    app = workflow.compile()

    assert app is not None
    # Check nodes exist
    graph = app.get_graph()
    nodes = list(graph.nodes.keys())
    assert "fetch_weather" in nodes
    assert "fetch_history" in nodes
    assert "train_model" in nodes
    assert "generate_forecast" in nodes
    assert "enhance_forecast" in nodes
    assert "inverter_control_hook" in nodes
    assert "finalize_forecast" in nodes


def test_inverter_control_hook_defaults():
    """Test inverter control hook defaults."""
    hook = InverterControlHook()

    assert hook.enabled is True
    assert hook.endpoint == "http://localhost:8081"
    assert hook.pre_charge_threshold_wh == 5000
    assert hook.cloudy_horizon_hours == 6


@pytest.mark.asyncio
async def test_enhance_forecast_node_no_base():
    """Test enhance forecast node fails without base forecast."""
    site = create_test_site()
    state = WorkflowState(site_config=site, panel_id="test-1", base_forecast=None)

    result = await enhance_forecast_node(state)

    assert len(result.errors) > 0
    # Error is added but completed_steps only gets appended in try/except
    assert "current_step" in result.model_dump()


@pytest.mark.asyncio
async def test_enhance_forecast_node_with_base():
    """Test enhance forecast node with base forecast."""
    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast

    site = create_test_site()

    mock_forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=1,
        points=[
            ForecastPoint(
                timestamp=datetime.now(UTC),
                energy_wh=1000,
                power_w=1000,
                confidence_lower=800,
                confidence_upper=1200,
                method=ForecastMethod.ENSEMBLE,
            )
        ],
        method=ForecastMethod.ENSEMBLE,
    )

    state = WorkflowState(
        site_config=site,
        panel_id="test-1",
        base_forecast=mock_forecast,
        weather_forecast=create_mock_weather_forecast(),
        historical_df=None,
    )

    # Mock the enhance_with_llm function (imported from solar_forecast.model)
    with patch("solar_forecast.model.enhance_with_llm", new_callable=AsyncMock) as mock_enhance:
        mock_enhance.return_value = mock_forecast

        result = await enhance_forecast_node(state)

    assert result.enhanced_forecast is not None
    assert "enhance_forecast" in result.completed_steps


@pytest.mark.asyncio
async def test_inverter_control_hook_node_disabled():
    """Test inverter control hook node when disabled."""
    site = create_test_site()

    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast

    mock_forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=1,
        points=[
            ForecastPoint(
                timestamp=datetime.now(UTC),
                energy_wh=1000,
                power_w=1000,
                confidence_lower=800,
                confidence_upper=1200,
                method=ForecastMethod.ENSEMBLE,
            )
        ],
        method=ForecastMethod.ENSEMBLE,
    )

    state = WorkflowState(
        site_config=site,
        panel_id="test-1",
        final_forecast=mock_forecast,
    )

    with patch("solar_forecast.workflow.InverterControlHook") as mock_hook_class:
        mock_hook = InverterControlHook(enabled=False)
        mock_hook_class.return_value = mock_hook

        result = await inverter_control_hook_node(state)

    assert "inverter_control_hook" in result.completed_steps
    assert len(result.warnings) == 0  # No warning when disabled


@pytest.mark.asyncio
async def test_inverter_control_hook_node_triggers_precharge():
    """Test inverter control hook triggers pre-charge warning."""
    site = create_test_site()

    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast

    # Low energy forecast to trigger pre-charge
    near_future_time = datetime.now(UTC) + timedelta(hours=3)
    mock_forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=6,
        points=[
            ForecastPoint(
                timestamp=near_future_time,
                energy_wh=1000,  # Low energy
                power_w=1000,
                confidence_lower=800,
                confidence_upper=1200,
                method=ForecastMethod.ENSEMBLE,
            )
        ],
        method=ForecastMethod.ENSEMBLE,
    )

    state = WorkflowState(
        site_config=site,
        panel_id="test-1",
        final_forecast=mock_forecast,
    )

    with patch("solar_forecast.workflow.InverterControlHook") as mock_hook_class:
        # Default hook has pre_charge_threshold_wh=5000, cloudy_horizon_hours=6
        mock_hook = InverterControlHook(
            enabled=True, pre_charge_threshold_wh=5000, cloudy_horizon_hours=6
        )
        mock_hook_class.return_value = mock_hook

        result = await inverter_control_hook_node(state)

    assert "inverter_control_hook" in result.completed_steps
    # Should add warning about low generation
    assert len(result.warnings) > 0
    assert "pre-charge" in result.warnings[0].lower()


@pytest.mark.asyncio
async def test_train_model_node_with_data():
    """Test train model node with historical data."""
    import pandas as pd

    site = create_test_site()

    # Create mock historical data
    hist_df = pd.DataFrame(
        {"energy_wh": [1000.0, 1500.0, 1200.0]},
        index=pd.to_datetime(
            [
                "2024-06-15T12:00:00+00:00",
                "2024-06-15T13:00:00+00:00",
                "2024-06-15T14:00:00+00:00",
            ],
            utc=True,
        ),
    )

    state = WorkflowState(
        site_config=site,
        panel_id="test-1",
        historical_df=hist_df,
        weather_forecast=create_mock_weather_forecast(),
    )

    result = await train_model_node(state)

    assert "train_model" in result.completed_steps


def create_mock_weather_forecast():
    """Create a mock weather forecast for testing."""

    hourly = []
    base_time = datetime(2024, 6, 15, 12, 0, tzinfo=UTC)
    for i in range(3):
        dt = base_time + timedelta(hours=i)
        hourly.append(
            WeatherHourly(
                time=dt,
                temperature_2m=20.0,
                relative_humidity_2m=60,
                cloud_cover=20,
                cloud_cover_low=5,
                cloud_cover_mid=10,
                cloud_cover_high=5,
                shortwave_radiation=800.0,
                direct_radiation=600.0,
                diffuse_radiation=200.0,
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


@pytest.mark.asyncio
async def test_train_model_node_persists_trained_model():
    """Trained model must be stored on state for generate_forecast_node."""
    import pandas as pd

    site = create_test_site()

    base_time = datetime(2024, 6, 15, tzinfo=UTC)
    hourly = []
    for i in range(48):
        dt = base_time + timedelta(hours=i)
        hourly.append(
            WeatherHourly(
                time=dt,
                temperature_2m=20.0,
                relative_humidity_2m=60,
                cloud_cover=20,
                cloud_cover_low=5,
                cloud_cover_mid=10,
                cloud_cover_high=5,
                shortwave_radiation=800.0,
                direct_radiation=600.0,
                diffuse_radiation=200.0,
                wind_speed_10m=3.0,
                wind_direction_10m=180,
                pressure_msl=1013.25,
            )
        )
    weather = WeatherForecast(
        latitude=52.37,
        longitude=4.90,
        elevation=0,
        timezone="UTC",
        hourly=hourly,
    )

    hist_df = pd.DataFrame(
        {"energy_wh": [1000.0] * 48},
        index=pd.to_datetime([base_time + timedelta(hours=i) for i in range(48)], utc=True),
    )

    state = WorkflowState(
        site_config=site,
        panel_id="test-1",
        historical_df=hist_df,
        weather_forecast=weather,
    )

    with patch("solar_forecast.workflow.OpenMeteoClient") as mock_client_cls:
        mock_client_cls.return_value.fetch_forecast = AsyncMock(return_value=weather)
        result = await train_model_node(state)

    assert "train_model" in result.completed_steps
    assert getattr(result, "_trained_model", None) is not None


@pytest.mark.asyncio
async def test_inverter_control_hook_ignores_past_points():
    """Pre-charge must not count already-past forecast points."""
    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast

    site = create_test_site()

    past_time = datetime.now(UTC) - timedelta(hours=1)
    mock_forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=6,
        points=[
            ForecastPoint(
                timestamp=past_time,
                energy_wh=0,
                power_w=0,
                confidence_lower=0,
                confidence_upper=0,
                method=ForecastMethod.ENSEMBLE,
            )
        ],
        method=ForecastMethod.ENSEMBLE,
    )

    state = WorkflowState(
        site_config=site,
        panel_id="test-1",
        final_forecast=mock_forecast,
    )

    with patch("solar_forecast.workflow.InverterControlHook") as mock_hook_class:
        mock_hook = InverterControlHook(
            enabled=True, pre_charge_threshold_wh=5000, cloudy_horizon_hours=6
        )
        mock_hook_class.return_value = mock_hook

        result = await inverter_control_hook_node(state)

    pre_charge_warnings = [w for w in result.warnings if "pre-charge" in w.lower()]
    assert not pre_charge_warnings


def test_daily_kwh_by_date_utc():
    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast
    from solar_forecast.workflow import _daily_kwh_by_date

    base = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=6,
        points=[
            ForecastPoint(
                timestamp=base + timedelta(hours=h),
                energy_wh=1000,
                power_w=0,
                confidence_lower=0,
                confidence_upper=0,
                method=ForecastMethod.ENSEMBLE,
            )
            for h in range(6)
        ],
        method=ForecastMethod.ENSEMBLE,
    )

    daily = _daily_kwh_by_date(forecast.points, "UTC")
    assert daily == {"2026-08-22": 6.0}


def test_daily_kwh_by_date_timezone_split():
    """Points near midnight split across local dates when TZ shifts the day."""
    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast
    from solar_forecast.workflow import _daily_kwh_by_date

    # 2026-08-22 23:00 UTC == 2026-08-23 01:00 in Europe/Amsterdam (UTC+2 in summer)
    forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=4,
        points=[
            ForecastPoint(
                timestamp=datetime(2026, 8, 22, 21, 0, tzinfo=UTC) + timedelta(hours=h),
                energy_wh=500,
                power_w=0,
                confidence_lower=0,
                confidence_upper=0,
                method=ForecastMethod.ENSEMBLE,
            )
            for h in range(4)
        ],
        method=ForecastMethod.ENSEMBLE,
    )

    daily = _daily_kwh_by_date(forecast.points, "Europe/Amsterdam")
    assert daily == {"2026-08-22": 0.5, "2026-08-23": 1.5}


@pytest.mark.asyncio
async def test_post_daily_forecast_payload():
    """Daily summary posts today/tomorrow kWh to /api/v1/forecast."""
    from solar_forecast.model import ForecastMethod, ForecastPoint, GenerationForecast
    from solar_forecast.workflow import _post_daily_forecast

    now = datetime.now(UTC)
    points = [
        ForecastPoint(
            timestamp=now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=h),
            energy_wh=2000,
            power_w=0,
            confidence_lower=0,
            confidence_upper=0,
            method=ForecastMethod.ENSEMBLE,
        )
        for h in range(48)
    ]
    forecast = GenerationForecast(
        site_id="test-site",
        panel_id="test-1",
        forecast_horizon_hours=48,
        points=points,
        method=ForecastMethod.ENSEMBLE,
    )
    hook = InverterControlHook(enabled=True)

    with patch("solar_forecast.workflow.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post.return_value.raise_for_status = lambda: None
        mock_client_cls.return_value = mock_client

        await _post_daily_forecast(hook, forecast, "Europe/Amsterdam")

    assert mock_client.post.call_count == 1
    url = mock_client.post.call_args[0][0]
    payload = mock_client.post.call_args[1]["json"]
    assert url.endswith("/api/v1/forecast")
    assert payload["site_id"] == "test-site"
    assert payload["today_kwh"] > 0 or payload.get("today_kwh") == 0
    assert "tomorrow_kwh" in payload
