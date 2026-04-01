"""Run guarded-live mode."""

from __future__ import annotations

import asyncio

from app.config import load_config
from app.logging_utils import configure_logging
from app.main import run_app


if __name__ == "__main__":
    config = load_config("configs/live.yaml")
    configure_logging(config.log)
    asyncio.run(run_app(config))

