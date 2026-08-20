import unittest
from types import SimpleNamespace

from module.extension_api.services.instance_control_service import (
    InstanceControlService,
)
from module.extension_api.services.instance_service import InstanceService


class FakeFacade:
    def __init__(self):
        self.manager = SimpleNamespace(alive=False, state=2)
        self.start_calls = 0
        self.stop_calls = 0

    def list_instance_names(self):
        return ["alas"]

    def require_instance(self, instance):
        if instance != "alas":
            raise AssertionError(instance)

    def get_instance_manager(self, _instance):
        return self.manager

    def get_instance_module(self, _instance):
        return "alas"

    def start_instance(self, _instance):
        self.start_calls += 1
        self.manager.alive = True
        self.manager.state = 1

    def stop_instance(self, _instance):
        self.stop_calls += 1
        self.manager.alive = False
        self.manager.state = 2
        return True


class TestInstanceControlService(unittest.TestCase):
    def setUp(self):
        self.facade = FakeFacade()
        self.service = InstanceControlService(
            self.facade, InstanceService(self.facade)
        )

    def test_start_and_stop_are_idempotent(self):
        started = self.service.start("alas")
        started_again = self.service.start("alas")
        stopped = self.service.stop("alas")
        stopped_again = self.service.stop("alas")

        self.assertTrue(started.changed)
        self.assertTrue(started.instance.running)
        self.assertFalse(started_again.changed)
        self.assertEqual(1, self.facade.start_calls)
        self.assertTrue(stopped.changed)
        self.assertFalse(stopped.instance.running)
        self.assertFalse(stopped_again.changed)
        self.assertEqual(1, self.facade.stop_calls)


if __name__ == "__main__":
    unittest.main()
