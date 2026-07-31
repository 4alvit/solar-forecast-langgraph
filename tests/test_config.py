"""Tests for config module."""

from solar_forecast.config import PanelConfig, SiteConfig, DEFAULT_SITE


def test_panel_config_valid():
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
    assert panel.name == "Test Panel"
    assert panel.azimuth == 180
    assert panel.capacity_kw == 5.0


def test_panel_config_azimuth_bounds():
    # Valid bounds
    PanelConfig(name="T", panel_id="1", azimuth=0, tilt=30, capacity_kw=1, module_count=1, latitude=0, longitude=0)
    PanelConfig(name="T", panel_id="1", azimuth=360, tilt=30, capacity_kw=1, module_count=1, latitude=0, longitude=0)

    # Invalid bounds
    import pytest
    with pytest.raises(ValueError):
        PanelConfig(name="T", panel_id="1", azimuth=-1, tilt=30, capacity_kw=1, module_count=1, latitude=0, longitude=0)
    with pytest.raises(ValueError):
        PanelConfig(name="T", panel_id="1", azimuth=361, tilt=30, capacity_kw=1, module_count=1, latitude=0, longitude=0)


def test_panel_config_tilt_bounds():
    import pytest
    with pytest.raises(ValueError):
        PanelConfig(name="T", panel_id="1", azimuth=180, tilt=-1, capacity_kw=1, module_count=1, latitude=0, longitude=0)
    with pytest.raises(ValueError):
        PanelConfig(name="T", panel_id="1", azimuth=180, tilt=91, capacity_kw=1, module_count=1, latitude=0, longitude=0)


def test_panel_config_capacity_positive():
    import pytest
    with pytest.raises(ValueError):
        PanelConfig(name="T", panel_id="1", azimuth=180, tilt=30, capacity_kw=0, module_count=1, latitude=0, longitude=0)
    with pytest.raises(ValueError):
        PanelConfig(name="T", panel_id="1", azimuth=180, tilt=30, capacity_kw=-1, module_count=1, latitude=0, longitude=0)


def test_effective_capacity():
    panel = PanelConfig(
        name="Test",
        panel_id="t1",
        azimuth=180,
        tilt=35,
        capacity_kw=5.0,
        module_count=14,
        latitude=52.37,
        longitude=4.90,
    )
    eff = panel.effective_capacity_kw()
    # 5.0 * 0.96 * (1-0.02) * (1-0.01) = 5.0 * 0.96 * 0.98 * 0.99 ≈ 4.67
    assert 4.6 < eff < 4.8


def test_site_config():
    site = SiteConfig(
        site_name="test-site",
        latitude=52.37,
        longitude=4.90,
        panels=[
            PanelConfig(name="P1", panel_id="p1", azimuth=180, tilt=35, capacity_kw=5.0, module_count=14, latitude=52.37, longitude=4.90),
            PanelConfig(name="P2", panel_id="p2", azimuth=270, tilt=30, capacity_kw=3.0, module_count=8, latitude=52.37, longitude=4.90),
        ],
    )
    assert site.site_name == "test-site"
    assert len(site.panels) == 2
    assert site.total_capacity_kw() > 0


def test_site_config_panel_by_id():
    site = SiteConfig(
        site_name="test",
        latitude=0,
        longitude=0,
        panels=[PanelConfig(name="P1", panel_id="p1", azimuth=180, tilt=30, capacity_kw=1, module_count=1, latitude=0, longitude=0)],
    )
    panel = site.panel_by_id("p1")
    assert panel is not None
    assert panel.panel_id == "p1"

    assert site.panel_by_id("nonexistent") is None


def test_default_site():
    assert DEFAULT_SITE.site_name == "victron-site"
    assert len(DEFAULT_SITE.panels) == 2
    assert DEFAULT_SITE.panel_by_id("south-roof") is not None
    assert DEFAULT_SITE.panel_by_id("west-roof") is not None