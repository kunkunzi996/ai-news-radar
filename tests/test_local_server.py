import unittest
from pathlib import Path

from scripts.local_server import CONFIG_FILENAME, refresh_command, validate_source_config


class LocalServerTests(unittest.TestCase):
    def test_validate_source_config_accepts_dashboard_config(self):
        payload = {
            "version": "1.0",
            "sources": [
                {
                    "id": "wewe_rss_maobidao",
                    "name": "猫笔刀",
                    "type": "wewe_rss",
                    "enabled": True,
                    "locator": "MP_WXS_3198966508",
                }
            ],
        }

        self.assertIs(validate_source_config(payload), payload)

    def test_validate_source_config_requires_sources_array(self):
        with self.assertRaises(ValueError):
            validate_source_config({"version": "1.0"})

    def test_validate_source_config_requires_source_id_and_name(self):
        with self.assertRaises(ValueError):
            validate_source_config({"sources": [{"id": "", "name": "Missing id"}]})
        with self.assertRaises(ValueError):
            validate_source_config({"sources": [{"id": "missing_name", "name": ""}]})

    def test_refresh_command_uses_fixed_local_update_script(self):
        root = Path("E:/AI-news-reader/ai-news-radar-run")

        command = refresh_command(root)

        self.assertTrue(command[0].endswith("python.exe") or command[0].endswith("python"))
        self.assertEqual(command[1], str(root / "scripts" / "update_news.py"))
        self.assertIn("--source-config", command)
        self.assertIn(CONFIG_FILENAME, command)
        self.assertIn("--all-time", command)


if __name__ == "__main__":
    unittest.main()
