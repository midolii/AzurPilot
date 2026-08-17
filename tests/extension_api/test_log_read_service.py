import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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


if __name__ == "__main__":
    unittest.main()
