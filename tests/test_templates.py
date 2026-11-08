"""Focused language/template checks for the integration billing engine."""
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "custom_components" / "jk51_billing"


class TemplateLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Template tests do not need Home Assistant's aiohttp dependency.
        cls.previous_aiohttp = sys.modules.get("aiohttp")
        sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
        package = types.ModuleType("jk51_billing_test")
        package.__path__ = [str(SOURCE)]
        sys.modules["jk51_billing_test"] = package
        spec = importlib.util.spec_from_file_location("jk51_billing_test.engine", SOURCE / "engine.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        sys.modules.pop("jk51_billing_test.transfer", None)
        sys.modules.pop("jk51_billing_test", None)
        if cls.previous_aiohttp is None:
            sys.modules.pop("aiohttp", None)
        else:
            sys.modules["aiohttp"] = cls.previous_aiohttp

    def test_language_defaults_to_finnish(self):
        self.module.CFG = {}
        self.assertEqual(self.module.configured_language(), "fi")

    def test_english_template_is_selected_and_renderable(self):
        self.module.CFG = {"language": "en"}
        language = self.module.configured_language()
        self.assertEqual(language, "en")
        invoice = self.module.mail_template(
            f"invoice_email-{language}.md", dict.fromkeys(re.findall(
                r"\$\{([^}]+)\}", (Path(self.module.TEMPLATE_ROOT) / f"invoice_email-{language}.md").read_text()), "value"))
        self.assertIn("# JK51 electricity invoice", invoice)
        self.assertIn("Monthly power fee", self.module.mail_template(
            f"pmax_row-{language}.md", {
                "month_label": "1/2026", "pmax_kw": "2.000",
                "peak_rate_eur_kw": "2.00", "power_eur": "4.00",
            }))

    def test_unknown_language_is_rejected(self):
        self.module.CFG = {"language": "sv"}
        with self.assertRaisesRegex(RuntimeError, "language must be 'fi' or 'en'"):
            self.module.configured_language()


if __name__ == "__main__":
    unittest.main()
