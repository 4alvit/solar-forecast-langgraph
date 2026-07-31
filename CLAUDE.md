# Solar Forecast LangGraph - Contributing Guidelines

## Project Overview
LangGraph workflow for solar forecasting:
- Weather data agent (OpenMeteo API)
- Historical generation data loader (from inverter-monitoring)
- Panel configuration schema (azimuth, tilt, capacity)
- Forecast model (statistical + LLM reasoning)
- Integration hook for inverter-control (pre-charge before cloudy periods)
- Accuracy tracking and feedback loop

## Pull Request Workflow
- Never push directly to `main` branch
- Create a feature branch from `main`
- Open a Pull Request (PR) targeting `main`
- Use GitHub CLI (`gh`) to review, approve, and merge PRs
- Ensure CI passes before merging
- Keep PRs focused and small

## File Ignoring
- `logs/` directory and `*.local.py` files are intentionally ignored via `.gitignore`

## Versioning
- Follow semantic versioning for releases
- Update `CHANGELOG.md` for notable changes

## Development Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

## Running Tests
```bash
pytest tests/ -v --cov=solar_forecast
```

## Key Architectural Decisions
- LangGraph for workflow orchestration (stateful, resumable)
- OpenMeteo for free weather API (no key required)
- Statistical baseline (ARIMA/Prophet) + LLM refinement
- Pydantic for all schemas (validation + serialization)
- Tenacity for resilient API calls