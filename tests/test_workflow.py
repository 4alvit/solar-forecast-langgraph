"""Tests for workflow module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from solar_forecast.config import PanelConfig, SiteConfig
from solar_forecast.workflow import (
    WorkflowState,
    InverterControlHook,
    build_forecast_workflow,
    fetch_weather_node,
    fetch_history_node,
    train_model_node,
    generate_forecast_node,
    finalize_forecast_node,
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
    from solar_forecast.model import GenerationForecast, ForecastMethod, ForecastPoint

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