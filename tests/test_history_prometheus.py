"""Tests for PrometheusGenerationLoader response parsing."""

# pylint: disable=protected-access

from datetime import UTC, datetime

import pytest

from solar_forecast.history import PrometheusGenerationLoader


@pytest.mark.asyncio
async def test_fetch_generation_parses_matrix(monkeypatch):
    payload = {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [{"metric": {}, "values": [[1756000000, "1200.5"], [1756000900, "-3"]]}],
        },
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, *_url, **_kwargs):
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    loader = PrometheusGenerationLoader()
    data = await loader.fetch_generation(
        "home",
        datetime.fromtimestamp(1755990000, tz=UTC),
        datetime.fromtimestamp(1756001000, tz=UTC),
    )

    assert len(data.records) == 2
    assert data.records[0].power_w == 1200.5
    # negative (night noise) clamped to 0
    assert data.records[1].power_w == 0.0
    assert data.interval_minutes == 15


@pytest.mark.asyncio
async def test_fetch_generation_empty(monkeypatch):
    loader = PrometheusGenerationLoader()

    class FakeResponse:
        status = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "success", "data": {"resultType": "matrix", "result": []}}

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, *_url, **_kwargs):
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    data = await loader.fetch_generation(
        "home",
        datetime.fromtimestamp(1755990000, tz=UTC),
        datetime.fromtimestamp(1756001000, tz=UTC),
    )

    assert data.records == []
