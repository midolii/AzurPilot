import threading
import unittest

from module.extension_api.errors import (
    CoreUpdateBusyError,
    CoreUpdateUnavailableError,
)
from module.extension_api.services.core_update_service import CoreUpdateService


class FakeUpdater:
    Branch = "api-main"
    Repository = "git@github.com:midolii/AzurPilot.git"

    def __init__(self):
        self.state = 1
        self.started = threading.Event()
        self.release = threading.Event()

    def get_commit(self, revision="", n=1, short_sha1=False):
        del revision, short_sha1
        commit = ("b6501dff9", "midolii", "2026-08-20 12:00:00 +0800", "feat(api)")
        return commit if n == 1 else [commit]

    def check_update(self):
        self.state = "checking"

    def run_update(self):
        self.started.set()
        self.release.wait(timeout=1)
        self.state = "finish"
        return True


class TestCoreUpdateService(unittest.TestCase):
    def test_snapshot_and_check_use_configured_update_source(self):
        updater = FakeUpdater()
        service = CoreUpdateService(updater, enabled_provider=lambda: True)

        snapshot = service.get()
        checking = service.check()

        self.assertEqual("api-main", snapshot.source_branch)
        self.assertEqual("b6501dff9", snapshot.history[0].sha1)
        self.assertEqual("checking", checking.status)

    def test_apply_runs_in_background_and_rejects_duplicates(self):
        updater = FakeUpdater()
        service = CoreUpdateService(updater, enabled_provider=lambda: True)

        snapshot = service.apply()
        self.assertTrue(updater.started.wait(timeout=1))
        self.assertEqual("starting", snapshot.status)
        with self.assertRaises(CoreUpdateBusyError):
            service.apply()
        updater.release.set()

    def test_apply_requires_safe_runtime_hooks(self):
        service = CoreUpdateService(FakeUpdater(), enabled_provider=lambda: False)

        with self.assertRaises(CoreUpdateUnavailableError):
            service.apply()


if __name__ == "__main__":
    unittest.main()
