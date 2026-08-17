import unittest
from types import SimpleNamespace

from module.extension_api.errors import InstanceNotFoundError
from module.extension_api.services.instance_service import InstanceService


class FakeFacade:
    def __init__(self):
        self.managers = {
            "alas": SimpleNamespace(state=1, alive=True),
            "farm": SimpleNamespace(state=3, alive=False),
        }

    def list_instance_names(self):
        return ["alas", "farm"]

    def get_instance_manager(self, instance):
        return self.managers[instance]

    def get_instance_module(self, instance):
        return "alas" if instance == "alas" else "maa"


class TestInstanceService(unittest.TestCase):
    def setUp(self):
        self.service = InstanceService(FakeFacade())

    def test_list_returns_stable_snapshots(self):
        snapshots = self.service.list()

        self.assertEqual(["alas", "farm"], [item.name for item in snapshots])
        self.assertEqual("running", snapshots[0].state)
        self.assertTrue(snapshots[0].running)
        self.assertEqual("warning", snapshots[1].state)
        self.assertFalse(snapshots[1].running)

    def test_get_rejects_unknown_instance(self):
        with self.assertRaises(InstanceNotFoundError):
            self.service.get("missing")


if __name__ == "__main__":
    unittest.main()
