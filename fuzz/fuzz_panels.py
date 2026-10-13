import math
import sys
import types
from pathlib import Path

import atheris

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("solar_forecast")
package.__path__ = [str(ROOT / "solar_forecast")]
sys.modules[package.__name__] = package

with atheris.instrument_imports():
    from solar_forecast.config import PanelConfig


def test_one_input(data: bytes) -> None:
    from pydantic import ValidationError

    try:
        panel = PanelConfig.model_validate_json(data)
    except ValidationError:
        return
    assert PanelConfig.model_validate_json(panel.model_dump_json()) == panel  # nosec B101 - intentional test oracle
    capacity = panel.effective_capacity_kw()
    assert math.isfinite(capacity) and capacity >= 0  # nosec B101 - intentional test oracle
    assert capacity <= panel.capacity_kw  # nosec B101 - intentional test oracle


if __name__ == "__main__":
    atheris.Setup(sys.argv, atheris.instrument_func(test_one_input))
    atheris.Fuzz()
