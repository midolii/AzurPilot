import unittest
from datetime import datetime

from module.extension_api.errors import DataReadError, InvalidLanguageError
from module.extension_api.services.config_read_service import ConfigReadService


class FakeFacade:
    def __init__(self):
        self.config = {
            "Alas": {
                "Emulator": {"PackageName": "com.bilibili.azurlane"},
                "Error": {
                    "LlmApiKey": "api-secret",
                    "LlmModel": "model",
                },
            },
            "Main": {
                "Scheduler": {
                    "Enable": True,
                    "Command": "Main",
                    "NextRun": datetime(2026, 8, 17, 12, 30),
                }
            },
        }
        self.args_reads = 0
        self.menu_reads = 0
        self.i18n_reads = 0

    def require_instance(self, _instance):
        return None

    def get_instance_module(self, _instance):
        return "alas"

    def read_instance_config(self, _instance):
        return self.config

    def get_supported_languages(self):
        return ("zh-CN", "en-US")

    def read_instance_menu(self, _instance):
        self.menu_reads += 1
        return {
            "MainMenu": {
                "page": "setting",
                "menu": "collapse",
                "tasks": ["Main", "HiddenTask"],
            }
        }

    def read_instance_args(self, _instance):
        self.args_reads += 1
        return {
            "Main": {
                "Campaign": {
                    "Stage": {
                        "type": "select",
                        "value": "12-4",
                        "option": ["12-4", "13-4"],
                        "option_cn": ["13-4"],
                    },
                    "ApiToken": {"type": "input", "value": ""},
                    "Internal": {
                        "type": "input",
                        "value": "hidden",
                        "display": "hide",
                    },
                    "Storage": {"type": "storage", "value": {}},
                }
            },
            "HiddenTask": {
                "Storage": {"Storage": {"type": "storage", "value": {}}}
            },
        }

    def read_instance_i18n(self, _instance, language):
        self.i18n_reads += 1
        return {
            "Menu": {"MainMenu": {"name": "主线菜单"}},
            "Task": {"Main": {"name": "主线", "help": "任务帮助"}},
            "Campaign": {
                "_info": {"name": "关卡", "help": "分组帮助"},
                "Stage": {
                    "name": "关卡名称",
                    "help": "字段帮助",
                    "13-4": "危险海域",
                },
                "ApiToken": {"name": "令牌", "help": ""},
            },
        }


class TestConfigReadService(unittest.TestCase):
    def setUp(self):
        self.facade = FakeFacade()
        self.service = ConfigReadService(self.facade)

    def test_config_snapshot_is_json_safe_and_redacted(self):
        snapshot = self.service.get_config("alas")

        self.assertIsNone(snapshot.values["Alas"]["Error"]["LlmApiKey"])
        self.assertEqual("model", snapshot.values["Alas"]["Error"]["LlmModel"])
        self.assertEqual(
            "2026-08-17T12:30:00",
            snapshot.values["Main"]["Scheduler"]["NextRun"],
        )
        self.assertEqual(("Alas.Error.LlmApiKey",), snapshot.redacted_paths)
        self.assertEqual("api-secret", self.facade.config["Alas"]["Error"]["LlmApiKey"])

    def test_schema_is_localized_filtered_and_cached(self):
        first = self.service.get_schema("alas", "zh-CN")
        second = self.service.get_schema("alas", "zh-CN")

        self.assertEqual("zh-CN", first.language)
        self.assertEqual("主线菜单", first.menus[0].display_name)
        self.assertEqual("Main", first.menus[0].tasks[0].name)
        fields = first.menus[0].tasks[0].groups[0].fields
        self.assertEqual(["Stage", "ApiToken"], [field.name for field in fields])
        self.assertEqual(["13-4"], [option.value for option in fields[0].options])
        self.assertEqual("危险海域", fields[0].options[0].label)
        self.assertTrue(fields[1].sensitive)
        self.assertEqual(first.menus, second.menus)
        self.assertEqual(1, self.facade.args_reads)
        self.assertEqual(1, self.facade.menu_reads)
        self.assertEqual(1, self.facade.i18n_reads)

    def test_unsupported_language_is_rejected(self):
        with self.assertRaises(InvalidLanguageError):
            self.service.get_schema("alas", "ja-JP")

    def test_upstream_error_is_converted(self):
        self.facade.read_instance_config = lambda _instance: (_ for _ in ()).throw(
            OSError("/private/config/path")
        )

        with self.assertRaises(DataReadError) as context:
            self.service.get_config("alas")

        self.assertNotIn("private", str(context.exception))


if __name__ == "__main__":
    unittest.main()
