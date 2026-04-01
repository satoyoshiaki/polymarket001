"""Run shadow-live mode."""

from __future__ import annotations

import asyncio

from app.config import load_config
from app.logging_utils import configure_logging
from app.main import run_app
from app.models import Mode


if __name__ == "__main__":
    config = load_config("configs/paper.yaml")
    config.mode = Mode.SHADOW_LIVE
    configure_logging(config.log)
    asyncio.run(run_app(config))

