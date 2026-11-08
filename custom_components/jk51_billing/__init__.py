"""Home Assistant integration for JK51 electricity billing."""

from __future__ import annotations

from pathlib import Path
import logging
from zoneinfo import ZoneInfo

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.event import async_track_utc_time_change
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN, SERVICE_COLLECT, SERVICE_INVOICE, SERVICE_TEST_DAY
from .runtime import async_run_action

_LOGGER = logging.getLogger(__name__)
_LOCAL = ZoneInfo("Europe/Helsinki")
_DATA_ENTRIES = "entries"
_SERVICES_REGISTERED = "services_registered"
_SERVICE_SCHEMA = vol.Schema({vol.Optional("config_entry_id"): str})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up service registry state."""
    hass.data.setdefault(DOMAIN, {_DATA_ENTRIES: {}})
    await _async_register_services(hass)
    return True


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register action services once for this HA instance."""
    domain_data = hass.data.setdefault(DOMAIN, {_DATA_ENTRIES: {}})
    if domain_data.get(_SERVICES_REGISTERED):
        return

    async def handle_action(call: ServiceCall, action: str) -> None:
        entries = domain_data[_DATA_ENTRIES]
        requested_id = call.data.get("config_entry_id")
        entry = entries.get(requested_id) if requested_id else next(iter(entries.values()), None)
        if entry is None:
            raise HomeAssistantError("JK51 billing is not configured or loaded")
        config = {**entry.data, **entry.options}
        data_dir = Path(hass.config.path("jk51_billing"))
        await async_run_action(hass, config, action, data_dir)

    async def handle_collect(call: ServiceCall) -> None:
        await handle_action(call, "collect")

    async def handle_test_day(call: ServiceCall) -> None:
        await handle_action(call, "test_day")

    async def handle_invoice(call: ServiceCall) -> None:
        await handle_action(call, "invoice")

    hass.services.async_register(DOMAIN, SERVICE_COLLECT, handle_collect, schema=_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_TEST_DAY, handle_test_day, schema=_SERVICE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_INVOICE, handle_invoice, schema=_SERVICE_SCHEMA)
    domain_data[_SERVICES_REGISTERED] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the configured integration entry."""
    domain_data = hass.data.setdefault(DOMAIN, {_DATA_ENTRIES: {}})
    domain_data[_DATA_ENTRIES][entry.entry_id] = entry

    # The custom panel is shared across entries and remains available after an
    # entry unload so it can show its setup prompt.
    from .panel import async_setup_panel

    await async_setup_panel(hass)

    async def dispatch(now):
        local = now.astimezone(_LOCAL)
        if local.hour != 4:
            return
        due = {"daily"}
        if local.weekday() == 0:
            due.add("weekly")
        if local.day == 1:
            due.add("monthly")
            if local.month in (1, 4, 7, 10):
                due.add("quarterly")
        # Each action reads the current entry so changes take effect immediately.
        for period in ("daily", "weekly", "monthly", "quarterly"):
            if period not in due or period not in entry.data.get("billing_periods", []):
                continue
            try:
                await async_run_action(hass, dict(entry.data), f"scheduled_billing_{period}", Path(hass.config.path("jk51_billing")))
            except Exception:
                _LOGGER.exception("Scheduled billing %s report failed", period)

    @callback
    def schedule_tick(now):
        hass.async_create_task(dispatch(now))

    # Helsinki is UTC+2 or UTC+3, so :30 UTC always includes 04:30 local.
    entry.async_on_unload(async_track_utc_time_change(hass, schedule_tick, minute=30, second=0))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an entry while leaving the setup panel available."""
    domain_data = hass.data.get(DOMAIN, {})
    domain_data.get(_DATA_ENTRIES, {}).pop(entry.entry_id, None)
    return True
