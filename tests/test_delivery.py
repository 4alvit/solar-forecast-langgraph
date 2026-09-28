"""Delivery retries preserve identity; timeouts never report acceptance."""

from unittest.mock import patch

import pytest

from solar_forecast.workflow import InverterControlHook, _trigger_pre_charge


@pytest.mark.asyncio
async def test_retry_and_recalculation_keep_daily_request_identity():
    hook = InverterControlHook(site_id="test-site")
    with patch(
        "solar_forecast.workflow.deliver",
        side_effect=[
            TimeoutError(),
            {"status": "duplicate"},
            {"status": "duplicate"},
            {"status": "accepted"},
        ],
    ) as send:
        assert (await _trigger_pre_charge(hook, 0, "2026-09-27"))["status"] == "duplicate"
        await _trigger_pre_charge(hook, 200, "2026-09-27")
        await _trigger_pre_charge(hook, 0, "2026-09-28")
    calls = send.call_args_list
    first, retry, recalculated, tomorrow = [call.args[3] for call in calls]
    assert first == retry
    assert first["request_id"] == recalculated["request_id"]
    assert first["request_id"] != tomorrow["request_id"]
    assert first["expires_at"] - first["issued_at"] == 300
    assert calls[0].kwargs["ack_topic"].endswith(first["request_id"])


@pytest.mark.asyncio
async def test_timeout_is_reported_as_delivery_failed():
    with patch("solar_forecast.workflow.deliver", side_effect=TimeoutError()) as send:
        result = await _trigger_pre_charge(InverterControlHook(), 0, "2026-09-27")
    assert result["status"] == "delivery_failed"
    assert send.call_count == 2
