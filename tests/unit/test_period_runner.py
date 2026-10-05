from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from retail_sim.simulation.period_runner import run_period


def test_run_period_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="date_from"):
        run_period(cast("Any", object()), date(2026, 6, 2), date(2026, 6, 1), 1)
