import math
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING

import atheris

# Typeshed does not yet re-export the instrumentation APIs at the package root.
if TYPE_CHECKING:
    from atheris.import_hook import instrument_imports
    from atheris.instrument_bytecode import instrument_func
else:
    instrument_imports = atheris.instrument_imports
    instrument_func = atheris.instrument_func

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("solar_forecast")
package.__path__ = [str(ROOT / "solar_forecast")]
sys.modules[package.__name__] = package

with instrument_imports():
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
    atheris.Setup(sys.argv, instrument_func(test_one_input))
    atheris.Fuzz()
