"""Tests for pricing choices in the integration setup flow."""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class FakeFlow:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def _async_current_entries(self):
        return []

    def async_show_form(self, **kwargs):
        return kwargs

    def async_create_entry(self, **kwargs):
        return kwargs


class FakeSchema:
    def __init__(self, fields):
        self.schema = fields


class ConfigFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def module(name, **attrs):
            item = types.ModuleType(name)
            item.__dict__.update(attrs)
            return item
        root = Path(__file__).resolve().parents[1] / 'custom_components' / 'jk51_billing'
        spec = importlib.util.spec_from_file_location('jk51_flow_test.const', root / 'const.py')
        const = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(const)
        marker = lambda key, **kwargs: key
        modules = {
            'voluptuous': module('voluptuous', Required=marker, Optional=marker, Schema=FakeSchema),
            'homeassistant': module('homeassistant', config_entries=module('homeassistant.config_entries', ConfigFlow=FakeFlow)),
            'homeassistant.core': module('homeassistant.core', callback=lambda fn: fn),
            'homeassistant.helpers': module('homeassistant.helpers', selector=MagicMock()),
            'jk51_flow_test': module('jk51_flow_test', __path__=[str(root)]),
            'jk51_flow_test.const': const,
        }
        cls.module_patch = patch.dict(sys.modules, modules)
        cls.module_patch.start()
        spec = importlib.util.spec_from_file_location('jk51_flow_test.config_flow', root / 'config_flow.py')
        cls.flow_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.flow_module)

    @classmethod
    def tearDownClass(cls):
        cls.module_patch.stop()

    def test_setup_asks_only_for_selected_price_source(self):
        for cost_type, present, absent in [
            ('spot', 'nordpool_entity', 'fixed_electricity_eur_per_kwh'),
            ('fixed', 'fixed_electricity_eur_per_kwh', 'nordpool_entity'),
        ]:
            with self.subTest(cost_type=cost_type):
                flow = self.flow_module.JK51BillingConfigFlow()
                result = asyncio.run(flow.async_step_user({'electricity_cost_type': cost_type}))
                self.assertEqual(result['step_id'], 'setup')
                self.assertIn(present, result['data_schema'].schema)
                self.assertNotIn(absent, result['data_schema'].schema)

    def test_fixed_price_is_validated_and_saved(self):
        flow = self.flow_module.JK51BillingConfigFlow()
        asyncio.run(flow.async_step_user({'electricity_cost_type': 'fixed'}))
        data = {'energy_entity': 'sensor.energy', 'fixed_electricity_eur_per_kwh': '0.10',
                'day_transfer_eur_per_kwh': '0.05', 'night_transfer_eur_per_kwh': '0.03',
                'monthly_fee_eur': '5', 'monthly_peak_eur_per_kw': '2',
                'spot_vat_multiplier': '1.25', 'electricity_margin_eur_per_kwh': '0.01',
                'recipient': 'bill@example.com', 'test_recipient': 'test@example.com'}
        result = asyncio.run(flow.async_step_setup(data))
        self.assertEqual(result['data']['electricity_cost_type'], 'fixed')
        self.assertEqual(result['data']['fixed_electricity_eur_per_kwh'], '0.10')
        self.assertEqual(result['data']['day_transfer_start'], '07:00')
        self.assertEqual(result['data']['day_transfer_end'], '22:00')
        data['fixed_electricity_eur_per_kwh'] = '-1'
        result = asyncio.run(flow.async_step_setup(data))
        self.assertEqual(result['errors']['base'], 'invalid_settings')


if __name__ == '__main__':
    unittest.main()
