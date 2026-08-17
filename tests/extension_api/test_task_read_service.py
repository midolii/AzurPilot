import unittest
from datetime import datetime
from types import SimpleNamespace

from module.extension_api.services.task_read_service import TaskReadService


class FakeFacade:
    def __init__(self, alive=True):
        self.manager = SimpleNamespace(alive=alive)
        self.config = {
            "Alas": {"Optimization": {"TaskHoardingDuration": 0}},
            "General": {
                "YukikazeTaskManager": {
                    "TaskPriorityAdjustment": "Research > Commission > Tactical"
                }
            },
            "Commission": {
                "Scheduler": {
                    "Enable": True,
                    "Command": "Commission",
                    "NextRun": datetime(2026, 8, 17, 9, 0),
                }
            },
            "Research": {
                "Scheduler": {
                    "Enable": True,
                    "Command": "Research",
                    "NextRun": datetime(2026, 8, 17, 8, 0),
                }
            },
            "Tactical": {
                "Scheduler": {
                    "Enable": True,
                    "Command": "Tactical",
                    "NextRun": datetime(2026, 8, 18, 8, 0),
                }
            },
            "Disabled": {
                "Scheduler": {
                    "Enable": False,
                    "Command": "Disabled",
                    "NextRun": "invalid",
                }
            },
            "Invalid": {
                "Scheduler": {
                    "Enable": True,
                    "Command": "Invalid",
                    "NextRun": "invalid",
                }
            },
        }

    def require_instance(self, _instance):
        return None

    def read_instance_config(self, _instance):
        return self.config

    def read_instance_args(self, _instance):
        tasks = {}
        for name in ("Commission", "Research", "Tactical", "Disabled", "Invalid"):
            tasks[name] = {
                "Scheduler": {"Command": {"value": name}}
            }
        return tasks

    def read_instance_i18n(self, _instance, _language):
        return {"Task": {"Research": {"name": "科研"}}}

    def get_instance_manager(self, _instance):
        return self.manager

    def get_current_time(self):
        return datetime(2026, 8, 17, 10, 0)


class TestTaskReadService(unittest.TestCase):
    def test_running_instance_separates_task_groups(self):
        snapshot = TaskReadService(FakeFacade(alive=True)).get("alas")

        self.assertEqual(["Research"], [item.name for item in snapshot.running])
        self.assertEqual(
            ["Commission", "Invalid"],
            [item.name for item in snapshot.pending],
        )
        self.assertEqual(["Tactical"], [item.name for item in snapshot.waiting])
        self.assertEqual(["Disabled"], [item.name for item in snapshot.disabled])
        self.assertEqual("科研", snapshot.running[0].display_name)
        self.assertIsNone(snapshot.pending[1].next_run)

    def test_stopped_instance_has_no_running_task(self):
        snapshot = TaskReadService(FakeFacade(alive=False)).get("alas")

        self.assertEqual((), snapshot.running)
        self.assertEqual(
            ["Research", "Commission", "Invalid"],
            [item.name for item in snapshot.pending],
        )

    def test_args_order_is_fallback_for_submodule(self):
        facade = FakeFacade(alive=False)
        facade.config["General"] = {}

        snapshot = TaskReadService(facade).get("alas")

        self.assertEqual("Commission", snapshot.pending[0].name)


if __name__ == "__main__":
    unittest.main()
