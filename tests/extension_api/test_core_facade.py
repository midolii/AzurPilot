import unittest
from unittest.mock import Mock, patch

from module.extension_api import core_facade as core_facade_module
from module.extension_api.core_facade import CoreFacade


class TestCoreFacade(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
