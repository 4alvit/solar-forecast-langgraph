"""A slow MQTT exchange must not monopolize the forecasting event loop."""

import asyncio
import threading
from unittest.mock import patch

import pytest

from solar_forecast.model import ForecastMethod, GenerationForecast
from solar_forecast.workflow import InverterControlHook, _post_daily_forecast, _trigger_pre_charge


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["precharge", "daily_forecast"])
async def test_event_loop_can_make_progress_while_mqtt_waits(operation):
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    progressed = []

    def slow_delivery(*args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        progressed.append(release.wait(2))
        return {"status": "accepted"}

    hook = InverterControlHook(site_id="test-site")
    forecast = GenerationForecast(
        site_id="test-site",
        panel_id=None,
        forecast_horizon_hours=48,
        points=[],
        method=ForecastMethod.ENSEMBLE,
    )
    with (
        patch("solar_forecast.workflow.deliver", side_effect=slow_delivery),
        patch("solar_forecast.workflow.MQTT_AVAILABLE", True),
    ):
        action = (
            _trigger_pre_charge(hook, 0, "2026-09-30")
            if operation == "precharge"
            else _post_daily_forecast(hook, forecast, "UTC")
        )
        task = asyncio.create_task(action)
        try:
            await asyncio.wait_for(started.wait(), 3)
            release.set()
            await asyncio.wait_for(task, 3)
        finally:
            release.set()
            if not task.done():
                await task
    assert progressed == [True], "MQTT waiting blocked the event loop's release callback"


@pytest.mark.asyncio
async def test_cancellation_does_not_schedule_another_precharge_attempt():
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()

    def interrupted_delivery(*args, **kwargs):
        try:
            loop.call_soon_threadsafe(started.set)
            if not release.wait(2):
                raise AssertionError("event loop did not handle cancellation")
            raise OSError("in-flight delivery failed")
        finally:
            finished.set()

    with patch("solar_forecast.workflow.deliver", side_effect=interrupted_delivery) as send:
        task = asyncio.create_task(_trigger_pre_charge(InverterControlHook(), 0, "2026-09-30"))
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
    assert send.call_count == 1
