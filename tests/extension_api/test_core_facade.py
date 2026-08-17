import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.extension_api import core_facade as core_facade_module
from module.extension_api.core_facade import CoreFacade, _get_config_updater_class


class TestCoreFacade(unittest.TestCase):
    def tearDown(self):
        _get_config_updater_class.cache_clear()

    def test_list_instance_names_is_stable_and_sorted(self):
        facade = CoreFacade()

        with patch(
            "module.extension_api.core_facade.alas_instance",
            return_value=["farm", "alas", "farm"],
        ):
            self.assertEqual(["alas", "farm"], facade.list_instance_names())

    def test_process_and_module_lookups_are_delegated(self):
        facade = CoreFacade()
        manager = Mock()

        with (
            patch.object(
                core_facade_module.ProcessManager,
                "get_manager",
                return_value=manager,
            ) as get_manager,
            patch(
                "module.extension_api.core_facade.get_config_mod",
                return_value="alas",
            ) as get_config_mod,
        ):
            self.assertIs(manager, facade.get_instance_manager("alas"))
            self.assertEqual("alas", facade.get_instance_module("alas"))

        get_manager.assert_called_once_with("alas")
        get_config_mod.assert_called_once_with("alas")

    def test_core_and_submodule_config_updaters_are_selected(self):
        class FakeUpdater:
            pass

        fake_module = SimpleNamespace(ConfigUpdater=FakeUpdater)

        self.assertIs(
            core_facade_module.ConfigUpdater,
            _get_config_updater_class("alas"),
        )
        with (
            patch(
                "module.extension_api.core_facade.get_mod_dir",
                side_effect={"maa": "AlasMaaBridge", "fpy": "AlasFpyBridge"}.get,
            ),
            patch(
                "module.extension_api.core_facade.importlib.import_module",
                return_value=fake_module,
            ) as import_module,
        ):
            self.assertIs(FakeUpdater, _get_config_updater_class("maa"))
            self.assertIs(FakeUpdater, _get_config_updater_class("fpy"))

        self.assertEqual(2, import_module.call_count)

    def test_read_instance_config_uses_read_only_updater_path(self):
        facade = CoreFacade()
        updater = Mock()
        updater.read_file.return_value = {"Main": {"Scheduler": {"Enable": True}}}

        with (
            patch.object(facade, "require_instance"),
            patch.object(facade, "get_instance_module", return_value="alas"),
            patch(
                "module.extension_api.core_facade._get_config_updater_class",
                return_value=Mock(return_value=updater),
            ),
        ):
            data = facade.read_instance_config("alas")

        self.assertTrue(data["Main"]["Scheduler"]["Enable"])
        updater.read_file.assert_called_once_with("alas")
        self.assertFalse(updater.write_file.called)

    def test_read_instance_documents_use_module_paths(self):
        facade = CoreFacade()

        with (
            patch.object(facade, "require_instance"),
            patch.object(facade, "get_instance_module", return_value="maa"),
            patch(
                "module.extension_api.core_facade.filepath_args",
                return_value="args-path",
            ) as args_path,
            patch(
                "module.extension_api.core_facade.filepath_i18n",
                return_value="i18n-path",
            ) as i18n_path,
            patch(
                "module.extension_api.core_facade.read_file",
                side_effect=lambda path: {"path": path},
            ),
        ):
            self.assertEqual({"path": "args-path"}, facade.read_instance_args("maa"))
            self.assertEqual(
                {"path": "i18n-path"},
                facade.read_instance_i18n("maa", "zh-CN"),
            )

        args_path.assert_called_once_with("args", "maa")
        i18n_path.assert_called_once_with("zh-CN", "maa")

    def test_log_renderables_are_copied(self):
        facade = CoreFacade()
        renderables = ["first"]
        manager = SimpleNamespace(renderables=renderables)

        with (
            patch.object(facade, "require_instance"),
            patch.object(facade, "get_instance_manager", return_value=manager),
        ):
            snapshot = facade.get_instance_log_renderables("alas")

        renderables.append("second")
        self.assertEqual(["first"], snapshot)

    def test_latest_log_file_is_scoped_to_log_directory(self):
        facade = CoreFacade()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            log_dir = root / "log"
            log_dir.mkdir()
            old = log_dir / "2026-08-16_alas.txt"
            new = log_dir / "2026-08-17_alas.txt"
            other = log_dir / "2026-08-18_other.txt"
            old.write_text("old", encoding="utf-8")
            new.write_text("new", encoding="utf-8")
            other.write_text("other", encoding="utf-8")
            old.touch()
            new.touch()

            with (
                patch.object(facade, "require_instance"),
                patch.object(core_facade_module, "PROJECT_ROOT", root),
            ):
                result = facade.get_latest_instance_log_file("alas")

        self.assertEqual("2026-08-17_alas.txt", result.name)


if __name__ == "__main__":
    unittest.main()
