"""Check the CLI output path against its declared runtime dependencies."""

import json

import pytest

from solar_forecast.main import aio_write_json


@pytest.mark.asyncio
async def test_cli_json_writer(tmp_path):
    output = tmp_path / "forecast.json"
    await aio_write_json(str(output), {"energy_wh": 1250.0})
    assert json.loads(output.read_text()) == {"energy_wh": 1250.0}
