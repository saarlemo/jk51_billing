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
            'jk51_panel_test': module('jk51_panel_test', __path__=[str(Path(__file__).resolve().parents[1] / 'custom_components' / 'jk51_billing')]),
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

    def test_transfer_times_are_saved_and_invalid_times_rejected(self):
        self.panel.save_config(self.hass, self.connection, {'id': 6, 'config': {
            'day_transfer_start': '06:00', 'day_transfer_end': '21:00'}})
        data = self.hass.config_entries.async_update_entry.call_args.kwargs['data']
        self.assertEqual((data['day_transfer_start'], data['day_transfer_end']), ('06:00', '21:00'))
        self.hass.config_entries.async_update_entry.reset_mock()
        self.panel.save_config(self.hass, self.connection, {'id': 7, 'config': {
            'day_transfer_start': '06:30', 'day_transfer_end': '21:00'}})
        self.hass.config_entries.async_update_entry.assert_not_called()
        self.assertIn('whole hours', self.connection.send_error.call_args.args[2])

    def test_saves_email_templates_and_rejects_invalid_fields(self):
        self.panel.save_config(self.hass, self.connection, {'id': 8, 'config': {
            'billing_name': 'House panel', 'email_subject_en': '${billing_name} ${identifier}',
            'email_body_en': '# ${billing_name}\nTotal: ${total_eur}'}})
        saved = self.hass.config_entries.async_update_entry.call_args.kwargs['data']
        self.assertEqual(saved['billing_name'], 'House panel')
        self.assertEqual(saved['email_body_en'], '# ${billing_name}\nTotal: ${total_eur}')
        for invalid in [
            {'email_body_en': '${not_a_field}'},
            {'email_body_fi': 'Invalid $'},
            {'email_subject_en': 'Bad\nsubject'},
            {'billing_name': 'Bad\nname'},
        ]:
            with self.subTest(invalid=invalid):
                self.hass.config_entries.async_update_entry.reset_mock()
                self.panel.save_config(self.hass, self.connection, {'id': 9, 'config': invalid})
                self.hass.config_entries.async_update_entry.assert_not_called()
                self.assertTrue(self.connection.send_error.called)

    def test_admin_can_load_default_templates(self):
        expected = {'fi': {'subject': 'subject', 'body': 'body'}}
        self.hass.async_add_executor_job = AsyncMock(return_value=expected)
        async def run():
            await self.panel.get_default_templates(self.hass, self.connection, {'id': 10})
        asyncio.run(run())
        self.connection.send_result.assert_called_once_with(10, expected)

    def test_non_admin_cannot_access_any_panel_command(self):
        self.connection.user.is_admin = False
        for handler, message in [(self.panel.get_config, {'id': 1}),
                                 (self.panel.save_config, {'id': 2, 'config': {}}),
                                 (self.panel.send_test, {'id': 3, 'period': 'monthly', 'value': '2026-01'}),
                                 (self.panel.get_default_templates, {'id': 4})]:
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
