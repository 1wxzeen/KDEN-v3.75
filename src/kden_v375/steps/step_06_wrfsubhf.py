"""Deprecated numeric compatibility surface for Step 05B Q05 state.

This entry point deliberately cannot start acquisition.  Q05 is owned by the
same Step 05 run, lock, worker ceiling, and archive transaction chain as the
hourly phase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..acquisition.records import verify_product_pass
from ..contracts import ContractError


def run(*_args: object, **_kwargs: object) -> None:
    raise ContractError(
        "Step 06 cannot start a second acquisition. Start or resume the owner-full "
        "Step 05 run; it enters Q05 automatically after the hourly product PASS."
    )


def verify_pass(project_root: Path | str) -> dict[str, Any]:
    return verify_product_pass(project_root, "wrfsubhf", deep=True)
