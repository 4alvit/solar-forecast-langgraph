"""Training workers must not block the loop or publish cancelled results."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from test_model import create_test_site, create_test_weather_forecast

from solar_forecast.model import ForecastModel
from solar_forecast.workflow import WorkflowState, train_model_node


def training_state(seeded):
    site = create_test_site()
    weather = create_test_weather_forecast(48)
    history = pd.DataFrame(
        {"energy_wh": [100.0]},
        index=pd.to_datetime([weather.hourly[0].time], utc=True),
    )
    state = WorkflowState(
        site_config=site,
        weather_forecast=weather,
        historical_df=history,
        warnings=["existing warning"],
        completed_steps=["fetch_history"],
    )
    previous = ForecastModel(site) if seeded else None
    if seeded:
        state._trained_model = previous
    return state, previous


def mocked_weather(state):
    return patch(
        "solar_forecast.workflow.OpenMeteoClient",
        return_value=SimpleNamespace(fetch_forecast=AsyncMock(return_value=state.weather_forecast)),
    )


@pytest.mark.asyncio
async def test_training_wait_allows_loop_progress_and_commits_only_on_completion():
    state, previous = training_state(False)
    model = ForecastModel(state.site_config)
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    progressed = []

    def slow_fit(weather, history):
        loop.call_soon_threadsafe(started.set)
        progressed.append(release.wait(2))
        assert weather is state.weather_forecast
        assert history is not state.historical_df
        return model

    with (
        mocked_weather(state),
        patch("solar_forecast.workflow.ForecastModel", return_value=model),
        patch.object(model, "train", side_effect=slow_fit),
    ):
        task = asyncio.create_task(train_model_node(state))
        try:
            await asyncio.wait_for(started.wait(), 3)
            assert not task.done(), "synchronous training monopolized the event loop"
            assert getattr(state, "_trained_model", None) is previous
            assert state.completed_steps == ["fetch_history"]
            release.set()
            assert await asyncio.wait_for(task, 3) is state
        finally:
            release.set()
            if not task.done():
                await task
    assert progressed == [True]
    assert state._trained_model is model
    assert state.completed_steps == ["fetch_history", "train_model"]
    assert state.warnings == ["existing warning"]


@pytest.mark.asyncio
@pytest.mark.parametrize("seeded", [False, True], ids=["fresh", "previous_model"])
async def test_training_value_error_preserves_fallback_and_previous_model(seeded):
    state, previous = training_state(seeded)
    with mocked_weather(state):
        result = await train_model_node(state)
    # Real fit() rejects the single historical hour before importing estimators.
    assert result is state
    assert getattr(state, "_trained_model", None) is previous
    assert state.completed_steps == ["fetch_history", "train_model"]
    assert state.warnings == [
        "existing warning",
        "Model training failed: Insufficient training data (need at least 24 hours)",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("seeded", [False, True], ids=["fresh", "previous_model"])
@pytest.mark.parametrize("worker_fails", [False, True], ids=["late_success", "late_failure"])
async def test_cancelled_training_cannot_publish_late_worker_result(seeded, worker_fails):
    state, previous = training_state(seeded)
    model = ForecastModel(state.site_config)
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()

    def late_fit(*args):
        try:
            loop.call_soon_threadsafe(started.set)
            assert release.wait(2), "event loop did not process cancellation"
            model.statistical.is_fitted = True
            if worker_fails:
                raise ValueError("late local fit failed")
            return model
        finally:
            finished.set()

    with (
        mocked_weather(state),
        patch("solar_forecast.workflow.ForecastModel", return_value=model),
        patch.object(model, "train", side_effect=late_fit),
    ):
        task = asyncio.create_task(train_model_node(state))
        try:
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not finished.is_set()
            assert getattr(state, "_trained_model", None) is previous
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)
            if not task.done():
                await task
    assert getattr(state, "_trained_model", None) is previous
    assert state.completed_steps == ["fetch_history"]
    assert state.warnings == ["existing warning"]
