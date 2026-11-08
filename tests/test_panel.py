"""Tests for panel WebSocket permissions and settings."""
import asyncio
import importlib.util
import sys
import types
import unittest
from functools import wraps
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


class Unauthorized(Exception):
    pass


def require_admin(func):
    @wraps(func)
    def guarded(hass, connection, msg):
        if connection.user is None or not connection.user.is_admin:
            raise Unauthorized
        return func(hass, connection, msg)
    return guarded


def async_response(func):
    @wraps(func)
    def schedule(hass, connection, msg):
        return asyncio.create_task(func(hass, connection, msg))
    return schedule


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def module(name, **attrs):
            item = types.ModuleType(name)
            item.__dict__.update(attrs)
            return item

        websocket = module('homeassistant.components.websocket_api',
                           websocket_command=lambda schema: lambda fn: fn,
                           require_admin=require_admin, async_response=async_response)
        modules = {
            'voluptuous': module('voluptuous', Required=lambda x: x, In=lambda x: x),
            'homeassistant': module('homeassistant'),
            'homeassistant.components': module('homeassistant.components', panel_custom=MagicMock(), websocket_api=websocket),
            'homeassistant.components.http': module('homeassistant.components.http', StaticPathConfig=MagicMock()),
            'homeassistant.core': module('homeassistant.core', HomeAssistant=object, callback=lambda fn: fn),
            'homeassistant.exceptions': module('homeassistant.exceptions', HomeAssistantError=RuntimeError),
            'jk51_panel_test': module('jk51_panel_test', __path__=[]),
            'jk51_panel_test.const': module('jk51_panel_test.const', DOMAIN='jk51_billing'),
            'jk51_panel_test.runtime': module('jk51_panel_test.runtime', async_run_action=AsyncMock()),
        }
        cls.module_patch = patch.dict(sys.modules, modules)
        cls.module_patch.start()
        path = Path(__file__).resolve().parents[1] / 'custom_components' / 'jk51_billing' / 'panel.py'
        spec = importlib.util.spec_from_file_location('jk51_panel_test.panel', path)
        cls.panel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.panel)

    @classmethod
    def tearDownClass(cls):
        cls.module_patch.stop()

    def setUp(self):
        self.hass = MagicMock()
        self.entry = MagicMock()
        self.entry.data = {'ha_token': 'private-token', 'gmail_app_password': 'private-password',
                           'language': 'fi', 'test_recipient': ['test@example.com']}
        self.hass.config_entries.async_entries.return_value = [self.entry]
        self.connection = MagicMock()
        self.connection.user.is_admin = True
        self.hass.config.path.return_value = '/config/jk51_billing'

    def test_admin_can_load_settings_without_disclosing_secrets(self):
        self.panel.get_config(self.hass, self.connection, {'id': 1})
        result = self.connection.send_result.call_args.args[1]
        self.assertEqual(result['language'], 'fi')
        self.assertNotIn('ha_token', result)
        self.assertNotIn('gmail_app_password', result)
        self.assertEqual(set(result['configured_secrets']), {'ha_token', 'gmail_app_password'})

    def test_admin_can_save_settings_and_keep_existing_secrets(self):
        self.panel.save_config(self.hass, self.connection,
                               {'id': 2, 'config': {'language': 'en', 'ha_token': ''}})
        data = self.hass.config_entries.async_update_entry.call_args.kwargs['data']
        self.assertEqual(data['language'], 'en')
        self.assertEqual(data['ha_token'], 'private-token')
        self.connection.send_result.assert_called_once_with(2)

    def test_fixed_price_mode_validates_and_saves_zero(self):
        self.panel.save_config(self.hass, self.connection, {'id': 4, 'config': {
            'electricity_cost_type': 'fixed', 'fixed_electricity_eur_per_kwh': 0}})
        data = self.hass.config_entries.async_update_entry.call_args.kwargs['data']
        self.assertEqual(data['electricity_cost_type'], 'fixed')
        self.assertEqual(data['fixed_electricity_eur_per_kwh'], 0)
        self.connection.send_result.assert_called_once_with(4)

    def test_switching_to_spot_requires_a_sensor(self):
        self.panel.save_config(self.hass, self.connection, {'id': 5, 'config': {
            'electricity_cost_type': 'spot'}})
        self.hass.config_entries.async_update_entry.assert_not_called()
        self.assertIn('spot price', self.connection.send_error.call_args.args[2])

    def test_non_admin_cannot_access_any_panel_command(self):
        self.connection.user.is_admin = False
        for handler, message in [(self.panel.get_config, {'id': 1}),
                                 (self.panel.save_config, {'id': 2, 'config': {}}),
                                 (self.panel.send_test, {'id': 3, 'period': 'monthly', 'value': '2026-01'})]:
            with self.subTest(handler=handler.__name__), self.assertRaises(Unauthorized):
                handler(self.hass, self.connection, message)
        self.connection.send_result.assert_not_called()

    def test_admin_can_send_manual_test(self):
        async def run():
            self.panel.async_run_action.reset_mock()
            await self.panel.send_test(self.hass, self.connection,
                                       {'id': 3, 'period': 'monthly', 'value': '2026-01'})
        asyncio.run(run())
        self.panel.async_run_action.assert_awaited_once()
        self.connection.send_result.assert_called_once_with(3)


if __name__ == '__main__':
    unittest.main()
