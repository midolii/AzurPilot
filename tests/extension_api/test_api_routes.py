import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.applications import Starlette
from starlette.testclient import TestClient

from module.extension_api.errors import (
    DataReadError,
    InvalidLanguageError,
    InvalidQueryError,
)
from module.extension_api.services.instance_service import InstanceService
from module.extension_api.types import (
    ConfigFieldSnapshot,
    ConfigGroupSnapshot,
    ConfigMenuSnapshot,
    ConfigSchemaSnapshot,
    ConfigSnapshot,
    ConfigTaskSnapshot,
    LogTailSnapshot,
    TaskListSnapshot,
    TaskSnapshot,
)
from module.extension_api.webapi import create_api_app


class FakeFacade:
    def __init__(self):
        self.managers = {
            "alas": SimpleNamespace(state=1, alive=True),
            "farm": SimpleNamespace(state=2, alive=False),
        }

    def list_instance_names(self):
        return ["alas", "farm"]

    def get_instance_manager(self, instance):
        return self.managers[instance]

    def get_instance_module(self, _instance):
        return "alas"

    def get_core_commit(self):
        return "857deff50"

    def get_python_version(self):
        return "3.14.6"

    def get_platform(self):
        return "linux"


class FakeConfigReadService:
    def get_config(self, instance):
        if instance == "broken":
            raise DataReadError("config")
        return ConfigSnapshot(
            instance=instance,
            module="alas",
            values={"Alas": {"Error": {"LlmApiKey": None}}},
            redacted_paths=("Alas.Error.LlmApiKey",),
        )

    def get_schema(self, instance, language=None):
        if language == "invalid":
            raise InvalidLanguageError(language)
        field = ConfigFieldSnapshot(
            key="Main.Campaign.Name",
            name="Name",
            display_name="关卡",
            help="",
            widget_type="input",
            default="12-4",
            options=(),
            display=None,
            read_only=False,
            sensitive=False,
        )
        group = ConfigGroupSnapshot(
            name="Campaign",
            display_name="关卡",
            help="",
            fields=(field,),
        )
        task = ConfigTaskSnapshot(
            name="Main",
            display_name="主线",
            help="",
            groups=(group,),
        )
        menu = ConfigMenuSnapshot(
            name="Main",
            display_name="主线",
            page="setting",
            menu_type=None,
            tasks=(task,),
        )
        return ConfigSchemaSnapshot(
            instance=instance,
            module="alas",
            language=language or "zh-CN",
            menus=(menu,),
        )


class FakeTaskReadService:
    def get(self, instance):
        task = TaskSnapshot(
            name="Main",
            display_name="主线",
            enabled=True,
            state="running",
            next_run=datetime(2026, 8, 17, 12, 0),
        )
        return TaskListSnapshot(
            instance=instance,
            running=(task,),
            pending=(),
            waiting=(),
            disabled=(),
        )


class FakeLogReadService:
    def get(self, instance, limit=None):
        if limit == "bad":
            raise InvalidQueryError("limit")
        return LogTailSnapshot(
            instance=instance,
            source="memory",
            lines=("line",),
            count=1,
            truncated=False,
        )


class TestApiRoutes(unittest.TestCase):
    def setUp(self):
        facade = FakeFacade()
        api = create_api_app(
            facade=facade,
            instance_service=InstanceService(facade),
            config_read_service=FakeConfigReadService(),
            task_read_service=FakeTaskReadService(),
            log_read_service=FakeLogReadService(),
        )
        application = Starlette()
        application.mount("/api/v1", api)
        self.client = TestClient(application)

    def test_health(self):
        response = self.client.get("/api/v1/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok", "apiVersion": "0.2.0"}, response.json())

    def test_system(self):
        response = self.client.get("/api/v1/system")

        self.assertEqual(200, response.status_code)
        self.assertEqual("857deff50", response.json()["coreCommit"])
        self.assertEqual("3.14.6", response.json()["pythonVersion"])
        self.assertEqual(
            [
                "instances",
                "instanceConfig",
                "instanceConfigSchema",
                "instanceTasks",
                "instanceLogs",
            ],
            response.json()["capabilities"],
        )

    def test_list_instances(self):
        response = self.client.get("/api/v1/instances")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [
                {
                    "name": "alas",
                    "module": "alas",
                    "running": True,
                    "state": "running",
                },
                {
                    "name": "farm",
                    "module": "alas",
                    "running": False,
                    "state": "inactive",
                },
            ],
            response.json()["items"],
        )

    def test_get_instance(self):
        response = self.client.get("/api/v1/instances/alas")

        self.assertEqual(200, response.status_code)
        self.assertEqual("running", response.json()["state"])

    def test_unknown_instance_returns_stable_error(self):
        response = self.client.get("/api/v1/instances/missing")

        self.assertEqual(404, response.status_code)
        self.assertEqual("instance_not_found", response.json()["error"]["code"])

    def test_get_instance_config(self):
        response = self.client.get("/api/v1/instances/alas/config")

        self.assertEqual(200, response.status_code)
        self.assertIsNone(response.json()["values"]["Alas"]["Error"]["LlmApiKey"])
        self.assertEqual(
            ["Alas.Error.LlmApiKey"], response.json()["redactedPaths"]
        )

    def test_get_instance_config_schema(self):
        response = self.client.get(
            "/api/v1/instances/alas/config/schema?lang=zh-CN"
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("zh-CN", response.json()["language"])
        self.assertEqual("Main.Campaign.Name", response.json()["menus"][0]["tasks"][0]["groups"][0]["fields"][0]["key"])

    def test_get_instance_tasks(self):
        response = self.client.get("/api/v1/instances/alas/tasks")

        self.assertEqual(200, response.status_code)
        self.assertEqual("running", response.json()["running"][0]["state"])
        self.assertEqual(
            "2026-08-17T12:00:00", response.json()["running"][0]["nextRun"]
        )

    def test_get_instance_logs(self):
        response = self.client.get("/api/v1/instances/alas/logs?limit=20")

        self.assertEqual(200, response.status_code)
        self.assertEqual(["line"], response.json()["lines"])
        self.assertEqual("memory", response.json()["source"])

    def test_invalid_language_returns_stable_error(self):
        response = self.client.get(
            "/api/v1/instances/alas/config/schema?lang=invalid"
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_language", response.json()["error"]["code"])

    def test_invalid_query_returns_stable_error(self):
        response = self.client.get("/api/v1/instances/alas/logs?limit=bad")

        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_query", response.json()["error"]["code"])

    def test_data_read_error_does_not_expose_details(self):
        response = self.client.get("/api/v1/instances/broken/config")

        self.assertEqual(500, response.status_code)
        self.assertEqual("data_read_failed", response.json()["error"]["code"])
        self.assertNotIn("config", response.json()["error"]["message"])

    def test_instance_data_routes_use_threadpool(self):
        async_mock = AsyncMock(
            side_effect=lambda function, *args: function(*args)
        )
        with patch(
            "module.extension_api.webapi.routes.instance_data.run_in_threadpool",
            async_mock,
        ):
            response = self.client.get("/api/v1/instances/alas/config")

        self.assertEqual(200, response.status_code)
        async_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
