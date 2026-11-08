"""Config flow for JK51 electricity billing."""

from __future__ import annotations

import math

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CC,
    CONF_DAY_TRANSFER,
    CONF_ENERGY_ENTITY,
    CONF_ELECTRICITY_COST_TYPE,
    CONF_FIXED_ELECTRICITY,
    CONF_GMAIL_PASSWORD,
    CONF_GMAIL_USER,
    CONF_HA_TOKEN,
    CONF_HA_URL,
    CONF_LANGUAGE,
    CONF_MARGIN,
    CONF_MONTHLY_FEE,
    CONF_MONTHLY_PEAK,
    CONF_NIGHT_TRANSFER,
    CONF_NORDPOOL_ENTITY,
    CONF_RECIPIENT,
    CONF_SPOT_VAT,
    CONF_TEST_RECIPIENT,
    DOMAIN,
)


def _schema(cost_type: str, defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}
    fields = {
        vol.Required(CONF_ENERGY_ENTITY, default=defaults.get(CONF_ENERGY_ENTITY)): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")
        ),
        vol.Required(CONF_DAY_TRANSFER, default=defaults.get(CONF_DAY_TRANSFER, "0.050")): str,
        vol.Required(CONF_NIGHT_TRANSFER, default=defaults.get(CONF_NIGHT_TRANSFER, "0.030")): str,
        vol.Required(CONF_MONTHLY_FEE, default=defaults.get(CONF_MONTHLY_FEE, "5.00")): str,
        vol.Required(CONF_MONTHLY_PEAK, default=defaults.get(CONF_MONTHLY_PEAK, "2.00")): str,
        # VAT treatment is contract-specific. Force an explicit entry.
        vol.Required(CONF_SPOT_VAT, default=defaults.get(CONF_SPOT_VAT, "")): str,
        vol.Required(CONF_MARGIN, default=defaults.get(CONF_MARGIN, "0.0")): str,
        vol.Required(CONF_LANGUAGE, default=defaults.get(CONF_LANGUAGE, "fi")): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["fi", "en"], mode=selector.SelectSelectorMode.DROPDOWN)
        ),
        vol.Required(CONF_RECIPIENT, default=defaults.get(CONF_RECIPIENT, "")): str,
        vol.Optional(CONF_CC, default=defaults.get(CONF_CC, "")): str,
        vol.Required(CONF_TEST_RECIPIENT, default=defaults.get(CONF_TEST_RECIPIENT, "")): str,
        vol.Required(CONF_GMAIL_USER, default=defaults.get(CONF_GMAIL_USER, "")): str,
        vol.Required(CONF_GMAIL_PASSWORD, default=defaults.get(CONF_GMAIL_PASSWORD, "")): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
        # The billing engine reads statistics through Home Assistant's API.
        vol.Required(CONF_HA_URL, default=defaults.get(CONF_HA_URL, "http://127.0.0.1:8123")): str,
        vol.Required(CONF_HA_TOKEN, default=defaults.get(CONF_HA_TOKEN, "")): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        ),
    }
    if cost_type == "spot":
        fields[vol.Required(CONF_NORDPOOL_ENTITY, default=defaults.get(CONF_NORDPOOL_ENTITY))] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")
        )
    else:
        fields[vol.Required(CONF_FIXED_ELECTRICITY, default=defaults.get(CONF_FIXED_ELECTRICITY, ""))] = str
    return vol.Schema(fields)


def _normalize(data: dict) -> dict:
    """Normalize recipient fields to the JSON format used by the engine."""
    normalized = dict(data)
    for key in (CONF_RECIPIENT, CONF_CC, CONF_TEST_RECIPIENT):
        value = normalized.get(key, "")
        normalized[key] = [item.strip() for item in value.split(",") if item.strip()]
    return normalized


def _validate(data: dict) -> dict:
    """Normalize and validate finite nonnegative rates and recipients."""
    normalized = _normalize(data)
    numeric_fields = (
        CONF_DAY_TRANSFER,
        CONF_NIGHT_TRANSFER,
        CONF_MONTHLY_FEE,
        CONF_MONTHLY_PEAK,
        CONF_SPOT_VAT,
        CONF_MARGIN,
    )
    rates = {key: float(normalized[key]) for key in numeric_fields}
    if any(not math.isfinite(value) or value < 0 for value in rates.values()):
        raise ValueError("negative_or_nonfinite_rate")
    if rates[CONF_SPOT_VAT] <= 0:
        raise ValueError("invalid_vat_multiplier")
    cost_type = normalized.get(CONF_ELECTRICITY_COST_TYPE, "spot")
    if cost_type == "fixed":
        price = float(normalized[CONF_FIXED_ELECTRICITY])
        if not math.isfinite(price) or price < 0:
            raise ValueError("invalid_fixed_price")
    elif cost_type == "spot":
        if not normalized.get(CONF_NORDPOOL_ENTITY):
            raise ValueError("missing_spot_sensor")
    else:
        raise ValueError("invalid_cost_type")
    if not normalized[CONF_RECIPIENT] or not normalized[CONF_TEST_RECIPIENT]:
        raise ValueError("recipients_required")
    return normalized


class JK51BillingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for JK51 billing."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            self.cost_type = user_input[CONF_ELECTRICITY_COST_TYPE]
            return await self.async_step_setup()
        schema = vol.Schema({vol.Required(CONF_ELECTRICITY_COST_TYPE, default="spot"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["spot", "fixed"], mode=selector.SelectSelectorMode.DROPDOWN)
        )})
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_setup(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            try:
                normalized = _validate({**user_input, CONF_ELECTRICITY_COST_TYPE: self.cost_type})
            except (KeyError, TypeError, ValueError):
                errors["base"] = "invalid_settings"
            else:
                return self.async_create_entry(title="JK51 Electricity Billing", data=normalized)
        return self.async_show_form(step_id="setup", data_schema=_schema(self.cost_type, user_input), errors=errors)
