import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.text import Text

from module.extension_api.errors import InvalidQueryError
from module.extension_api.services.log_read_service import LogReadService


class FakeFacade:
    def __init__(self):
        self.config = {"Alas": {"Error": {"LlmApiKey": "secret-value"}}}
        self.renderables = []
        self.log_file = None

    def require_instance(self, _instance):
        return None

    def read_instance_config(self, _instance):
        return self.config

    def get_instance_log_renderables(self, _instance):
        return list(self.renderables)

    def get_latest_instance_log_file(self, _instance):
        return self.log_file


class TestLogReadService(unittest.TestCase):
    def setUp(self):
        self.facade = FakeFacade()
        self.service = LogReadService(self.facade)

    def test_memory_tail_is_ordered_limited_and_redacted(self):
        self.facade.renderables = [
            "first",
            "second secret-value",
            "third",
        ]

        snapshot = self.service.get("alas", 2)

        self.assertEqual("memory", snapshot.source)
        self.assertEqual(("second [REDACTED]", "third"), snapshot.lines)
        self.assertEqual(2, snapshot.count)
        self.assertTrue(snapshot.truncated)
        self.assertEqual("plain", snapshot.format)

    def test_file_is_used_when_memory_is_empty(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-17_alas.txt"
            path.write_text("one\ntwo\nthree\n", encoding="utf-8")
            self.facade.log_file = path

            snapshot = self.service.get("alas", "2")

        self.assertEqual("file", snapshot.source)
        self.assertEqual(("two", "three"), snapshot.lines)
        self.assertTrue(snapshot.truncated)

    def test_empty_log_is_successful(self):
        snapshot = self.service.get("alas")

        self.assertEqual("none", snapshot.source)
        self.assertEqual((), snapshot.lines)
        self.assertFalse(snapshot.truncated)

    def test_invalid_limit_is_rejected(self):
        for value in ("0", "401", "2.5", "abc", True):
            with self.subTest(value=value), self.assertRaises(InvalidQueryError):
                self.service.get("alas", value)

    def test_ansi_memory_logs_include_millisecond_timestamps(self):
        self.facade.renderables = [
            Text("INFO  2026-08-18 11:36:19.654 │ [任务] 开始", style="cyan"),
        ]

        snapshot = self.service.get("alas", output_format="ansi")

        expected = int(datetime(2026, 8, 18, 11, 36, 19, 654000).astimezone().timestamp() * 1000)
        self.assertEqual("ansi", snapshot.format)
        self.assertIn("\x1b[", snapshot.lines[0])
        self.assertEqual(expected, snapshot.entries[0].timestamp_ms)

    def test_ansi_redaction_falls_back_to_safe_plain_text(self):
        self.facade.renderables = [Text("secret-value", style="magenta")]

        snapshot = self.service.get("alas", output_format="ansi")

        self.assertEqual(("[REDACTED]",), snapshot.lines)

    def test_invalid_output_format_is_rejected(self):
        with self.assertRaises(InvalidQueryError):
            self.service.get("alas", output_format="html")


if __name__ == "__main__":
    unittest.main()
