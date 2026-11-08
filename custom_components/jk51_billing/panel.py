"""Administrator-only configuration panel and WebSocket API."""
from pathlib import Path
import math

import voluptuous as vol
from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .runtime import async_run_action

from .const import DOMAIN
from .transfer import day_window
from .email_templates import default_templates, validate_template

PANEL = "jk51-billing"
FIELDS = {
    "ha_url", "ha_token", "energy_entity", "nordpool_entity", "electricity_cost_type", "fixed_electricity_eur_per_kwh",
    "day_transfer_eur_per_kwh", "night_transfer_eur_per_kwh", "day_transfer_start", "day_transfer_end", "monthly_fee_eur",
    "monthly_peak_eur_per_kw", "electricity_margin_eur_per_kwh", "spot_vat_multiplier",
    "recipient", "cc", "test_recipient", "test_cc", "billing_periods", "gmail_user", "gmail_app_password", "language",
    "billing_name", "email_subject_fi", "email_subject_en", "email_body_fi", "email_body_en",
}
SECRETS = {"ha_token", "gmail_app_password"}
NUMBERS = {"fixed_electricity_eur_per_kwh", "day_transfer_eur_per_kwh", "night_transfer_eur_per_kwh", "monthly_fee_eur", "monthly_peak_eur_per_kw", "electricity_margin_eur_per_kwh", "spot_vat_multiplier"}


def _entry(hass):
    entries = hass.config_entries.async_entries(DOMAIN)
    if len(entries) != 1:
        raise ValueError("Set up exactly one JK51 Billing integration first")
    return entries[0]


@websocket_api.websocket_command({vol.Required("type"): "jk51_billing/config/get"})
@websocket_api.require_admin
@callback
def get_config(hass, connection, msg):
    try:
        data = dict(_entry(hass).data)
        result = {key: value for key, value in data.items() if key in FIELDS - SECRETS}
        result["configured_secrets"] = [key for key in SECRETS if data.get(key)]
        connection.send_result(msg["id"], result)
    except ValueError as err:
        connection.send_error(msg["id"], "not_configured", str(err))


@websocket_api.websocket_command({vol.Required("type"): "jk51_billing/config/save", vol.Required("config"): dict})
@websocket_api.require_admin
@callback
def save_config(hass, connection, msg):
    try:
        entry = _entry(hass)
        incoming = msg["config"]
        if set(incoming) - FIELDS:
            raise ValueError("Unknown configuration field")
        data = dict(entry.data)
        for key, value in incoming.items():
            if key in SECRETS and value == "":
                continue
            if key in NUMBERS:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be a number") from None
                if not math.isfinite(number) or number < 0 or (key == "spot_vat_multiplier" and number <= 0):
                    raise ValueError(f"Invalid value for {key}")
                value = number
            elif key in {"recipient", "cc", "test_recipient", "test_cc"}:
                if not isinstance(value, list) or any(not isinstance(x, str) or "@" not in x or "\n" in x or "\r" in x for x in value):
                    raise ValueError(f"Invalid addresses in {key}")
            elif key == "billing_periods":
                if not isinstance(value, list) or any(period not in {"monthly", "quarterly"} for period in value) or len(value) != len(set(value)):
                    raise ValueError(f"Invalid periods in {key}")
            elif not isinstance(value, str):
                raise ValueError(f"{key} must be text")
            data[key] = value
        name = data.get("billing_name", "JK51")
        if not name.strip() or "\n" in name or "\r" in name:
            raise ValueError("Billing name must be a non-empty single line")
        for language in ("fi", "en"):
            validate_template(data.get(f"email_subject_{language}", ""), subject=True)
            validate_template(data.get(f"email_body_{language}", ""))
        day_start, day_end = day_window(data)
        if "day_transfer_start" in incoming or "day_transfer_end" in incoming:
            data["day_transfer_start"], data["day_transfer_end"] = day_start, day_end
        cost_type = data.get("electricity_cost_type", "spot")
        if cost_type not in ("spot", "fixed"):
            raise ValueError("Choose spot or fixed electricity pricing")
        if "electricity_cost_type" in incoming:
            if cost_type == "spot" and not data.get("nordpool_entity"):
                raise ValueError("Choose a spot price statistics sensor")
            if cost_type == "fixed" and data.get("fixed_electricity_eur_per_kwh") is None:
                raise ValueError("Enter a fixed electricity price")
        if data.get("language", "fi") not in ("fi", "en"):
            raise ValueError("Unsupported template language")
        hass.config_entries.async_update_entry(entry, data=data)
        connection.send_result(msg["id"])
    except (ValueError, TypeError) as err:
        connection.send_error(msg["id"], "invalid_config", str(err))


@websocket_api.websocket_command({vol.Required("type"): "jk51_billing/templates/defaults"})
@websocket_api.require_admin
@websocket_api.async_response
async def get_default_templates(hass, connection, msg):
    """Return the bundled templates for the email editor."""
    connection.send_result(msg["id"], await hass.async_add_executor_job(default_templates))


@websocket_api.websocket_command({
    vol.Required("type"): "jk51_billing/test/send",
    vol.Required("period"): vol.In(["monthly", "quarterly"]),
    vol.Required("value"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def send_test(hass, connection, msg):
    """Send an explicitly requested test using saved settings only."""
    try:
        entry = _entry(hass)
        await async_run_action(hass, dict(entry.data), "manual_test",
                               Path(hass.config.path("jk51_billing")), msg["period"], msg["value"])
        connection.send_result(msg["id"])
    except (ValueError, HomeAssistantError) as err:
        connection.send_error(msg["id"], "test_failed", str(err))


async def async_setup_panel(hass: HomeAssistant):
    """Register one panel and its commands for the lifetime of Home Assistant."""
    if hass.data.get(f"{DOMAIN}_panel_registered"):
        return
    await hass.http.async_register_static_paths([StaticPathConfig(
        "/jk51_billing_panel", str(Path(__file__).parent / "frontend"), False
    )])
    websocket_api.async_register_command(hass, get_config)
    websocket_api.async_register_command(hass, save_config)
    websocket_api.async_register_command(hass, send_test)
    websocket_api.async_register_command(hass, get_default_templates)
    await panel_custom.async_register_panel(
        hass, webcomponent_name="jk51-billing-panel", frontend_url_path=PANEL,
        sidebar_title="Electricity billing", sidebar_icon="mdi:lightning-bolt",
        module_url="/jk51_billing_panel/panel.js?v=7", require_admin=True,
    )
    hass.data[f"{DOMAIN}_panel_registered"] = True
