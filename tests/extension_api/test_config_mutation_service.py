import unittest
from datetime import datetime
from types import SimpleNamespace

from module.extension_api.errors import (
    ConfigRevisionConflictError,
    ConfigValidationError,
    TaskDisabledError,
    TaskNotFoundError,
)
from module.extension_api.services.config_mutation_service import (
    ConfigMutationService,
)
from module.extension_api.services.config_read_service import config_revision
from module.extension_api.types import (
    ConfigChange,
    ConfigFieldSnapshot,
    ConfigGroupSnapshot,
    ConfigMenuSnapshot,
    ConfigSchemaSnapshot,
    ConfigSnapshot,
    ConfigTaskSnapshot,
)


class FakeUpdater:
    def save_callback(self, key, value):
        if key == "Main.Campaign.Name":
            yield "Main.Campaign.Mode", f"mode:{value}"


class FakeFacade:
    def __init__(self):
        self.config = {
            "Main": {
                "Scheduler": {
                    "Enable": True,
                    "Command": "Main",
                    "NextRun": datetime(2026, 8, 21, 12, 0),  # noqa: DTZ001
                },
                "Campaign": {"Name": "12-4", "Mode": "normal"},
            },
            "Disabled": {
                "Scheduler": {
                    "Enable": False,
                    "Command": "Disabled",
                    "NextRun": datetime(2026, 8, 21, 13, 0),  # noqa: DTZ001
                }
            },
        }
        self.args = {
            "Main": {
                "Campaign": {
                    "Name": {
                        "type": "select",
                        "value": "12-4",
                        "option": ["12-4", "13-4"],
                    },
                    "ReadOnly": {
                        "type": "input",
                        "value": "fixed",
                        "display": "readonly",
                    },
                }
            }
        }
        self.manager = SimpleNamespace(alive=True)
        self.updater = FakeUpdater()

    def require_instance(self, instance):
        if instance != "alas":
            raise AssertionError(instance)

    def read_instance_config(self, _instance):
        return self.config

    def read_instance_args(self, _instance):
        return self.args

    def get_config_updater(self, _instance):
        return self.updater

    def write_instance_config(self, _instance, data):
        self.config = data

    def get_current_time(self):
        return datetime(2026, 8, 20, 12, 30, 45, 123456)  # noqa: DTZ001

    def get_instance_manager(self, _instance):
        return self.manager


class FakeReadService:
    def __init__(self, facade):
        self.facade = facade

    def get_schema(self, instance, _language=None):
        fields = (
            ConfigFieldSnapshot(
                key="Main.Campaign.Name",
                name="Name",
                display_name="关卡",
                help="",
                widget_type="select",
                default="12-4",
                options=(),
                display=None,
                read_only=False,
                sensitive=False,
            ),
            ConfigFieldSnapshot(
                key="Main.Campaign.ReadOnly",
                name="ReadOnly",
                display_name="只读",
                help="",
                widget_type="input",
                default="fixed",
                options=(),
                display="readonly",
                read_only=True,
                sensitive=False,
            ),
        )
        return ConfigSchemaSnapshot(
            instance=instance,
            module="alas",
            language="zh-CN",
            menus=(
                ConfigMenuSnapshot(
                    name="Main",
                    display_name="主线",
                    page="setting",
                    menu_type=None,
                    tasks=(
                        ConfigTaskSnapshot(
                            name="Main",
                            display_name="主线",
                            help="",
                            groups=(
                                ConfigGroupSnapshot(
                                    name="Campaign",
                                    display_name="关卡",
                                    help="",
                                    fields=fields,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

    def get_config(self, instance):
        return ConfigSnapshot(
            instance=instance,
            module="alas",
            values=self.facade.config,
            redacted_paths=(),
            revision=config_revision(self.facade.config),
        )


class TestConfigMutationService(unittest.TestCase):
    def setUp(self):
        self.facade = FakeFacade()
        self.service = ConfigMutationService(
            self.facade, FakeReadService(self.facade)
        )

    def test_patch_uses_revision_validation_and_save_callbacks(self):
        revision = config_revision(self.facade.config)

        result = self.service.patch(
            "alas",
            revision,
            (ConfigChange(path="Main.Campaign.Name", value="13-4"),),
        )

        self.assertEqual("13-4", self.facade.config["Main"]["Campaign"]["Name"])
        self.assertEqual(
            "mode:13-4", self.facade.config["Main"]["Campaign"]["Mode"]
        )
        self.assertNotEqual(revision, result.revision)

    def test_patch_rejects_stale_revision_and_read_only_path(self):
        with self.assertRaises(ConfigRevisionConflictError):
            self.service.patch(
                "alas",
                "stale",
                (ConfigChange(path="Main.Campaign.Name", value="13-4"),),
            )

        with self.assertRaises(ConfigValidationError):
            self.service.patch(
                "alas",
                config_revision(self.facade.config),
                (ConfigChange(path="Main.Campaign.ReadOnly", value="changed"),),
            )

    def test_run_now_updates_enabled_task_without_starting_worker(self):
        result = self.service.run_task_now("alas", "Main")

        self.assertEqual(
            datetime(2026, 8, 20, 12, 30, 45),  # noqa: DTZ001
            self.facade.config["Main"]["Scheduler"]["NextRun"],
        )
        self.assertTrue(result.scheduler_running)

    def test_run_now_rejects_disabled_or_unknown_task(self):
        with self.assertRaises(TaskDisabledError):
            self.service.run_task_now("alas", "Disabled")
        with self.assertRaises(TaskNotFoundError):
            self.service.run_task_now("alas", "Missing")


if __name__ == "__main__":
    unittest.main()
