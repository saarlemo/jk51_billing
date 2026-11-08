"""Action runner for the JK51 billing services."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)


async def async_run_action(
    hass: HomeAssistant, config: dict, action: str, data_dir: Path, start=None, end=None
) -> None:
    """Run a billing action with persisted integration settings.

    The billing engine runs filesystem, database and email operations outside
    Home Assistant's event loop.
    """
    try:
        from .engine import async_run_action as engine_run_action
    except ImportError as err:
        raise HomeAssistantError(
            "The JK51 billing engine is missing from this integration installation."
        ) from err

    try:
        await engine_run_action(hass, config, action, data_dir, start, end)
    except Exception as err:
        _LOGGER.exception("JK51 billing action %s failed", action)
        raise HomeAssistantError(f"JK51 billing {action} failed: {err}") from err
