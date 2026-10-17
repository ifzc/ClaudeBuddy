import json
import tempfile
import unittest
from pathlib import Path

from desktop_timezone.configuration import default_config, load_config, save_config


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "config.json"

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_missing_file_has_independent_defaults(self):
        first = load_config(self.path)
        first["apps"]["feishu"]["timeZone"] = "UTC"
        self.assertEqual(first["apps"]["weixin"]["timeZone"], "Asia/Shanghai")
        self.assertEqual(load_config(self.path), default_config())

    def test_partial_configuration_keeps_other_app_default(self):
        self.write({"apps": {"weixin": {"timeZone": "America/Phoenix"}}})
        config = load_config(self.path)
        self.assertEqual(config["apps"]["weixin"]["timeZone"], "America/Phoenix")
        self.assertEqual(config["apps"]["feishu"]["timeZone"], "Asia/Shanghai")

    def test_invalid_shapes_and_values_are_rejected(self):
        for value in [
            [],
            {"apps": []},
            {"apps": {"weixin": None}},
            {"apps": {"weixin": {"timeZone": []}}},
            {"apps": {"weixin": {"timeZone": "Missing/Zone"}}},
            {"apps": {"weixin": {"executable": 42}}},
        ]:
            with self.subTest(value=value):
                self.write(value)
                with self.assertRaises(ValueError):
                    load_config(self.path)

    def test_atomic_round_trip_preserves_custom_path(self):
        config = default_config()
        config["apps"]["weixin"]["executable"] = r"D:\Applications\Weixin\Weixin.exe"
        save_config(self.path, config)
        self.assertEqual(load_config(self.path), config)
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())
