import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.applications import Starlette
from starlette.testclient import TestClient

from module.extension_api.errors import (
    ConfigRevisionConflictError,
    DataReadError,
    InstanceNotFoundError,
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
    CoreCommitSnapshot,
    CoreUpdateSnapshot,
    InstanceActionSnapshot,
    InstanceSnapshot,
    LogLineSnapshot,
    LogTailSnapshot,
    TaskActionSnapshot,
    TaskListSnapshot,
    TaskSnapshot,
)
from module.extension_api.webapi import create_api_app
from module.extension_api.webapi.models import LogTailResponse
from module.extension_api.webapi.routes.instance_data import _serialize_log_event


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
        if instance == "missing":
            raise InstanceNotFoundError(instance)
        if instance == "broken":
            raise DataReadError("config")
        return ConfigSnapshot(
            instance=instance,
            module="alas",
            values={"Alas": {"Error": {"LlmApiKey": None}}},
            redacted_paths=("Alas.Error.LlmApiKey",),
            revision="a" * 64,
        )

    def get_schema(self, instance, language=None):
        if instance == "missing":
            raise InstanceNotFoundError(instance)
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
        if instance == "missing":
            raise InstanceNotFoundError(instance)
        task = TaskSnapshot(
            name="Main",
            display_name="主线",
            enabled=True,
            state="running",
            next_run=datetime(2026, 8, 17, 12, 0),  # noqa: DTZ001
        )
        return TaskListSnapshot(
            instance=instance,
            running=(task,),
            pending=(),
            waiting=(),
            disabled=(),
        )


class FakeLogReadService:
    def get(self, instance, limit=None, output_format=None):
        if instance == "missing":
            raise InstanceNotFoundError(instance)
        if limit == "bad":
            raise InvalidQueryError("limit")
        return LogTailSnapshot(
            instance=instance,
            source="memory",
            lines=("line",),
            count=1,
            truncated=False,
            format=output_format or "plain",
            entries=(LogLineSnapshot(content="line", timestamp_ms=1_777_000_000_123),),
        )


class FakeConfigMutationService:
    def patch(self, instance, expected_revision, changes):
        if expected_revision == "b" * 64:
            raise ConfigRevisionConflictError
        return ConfigSnapshot(
            instance=instance,
            module="alas",
            values={changes[0].path: changes[0].value},
            redacted_paths=(),
            revision="c" * 64,
        )

    def run_task_now(self, instance, task):
        return TaskActionSnapshot(
            instance=instance,
            task=task,
            action="runNow",
            scheduled_at=datetime(2026, 8, 20, 12, 0),  # noqa: DTZ001
            scheduler_running=True,
        )


class FakeInstanceControlService:
    def start(self, instance):
        return self._result(instance, "start", True)

    def stop(self, instance):
        return self._result(instance, "stop", False)

    @staticmethod
    def _result(instance, action, running):
        return InstanceActionSnapshot(
            action=action,
            changed=True,
            instance=InstanceSnapshot(
                name=instance,
                module="alas",
                running=running,
                state="running" if running else "inactive",
            ),
        )


class FakeCoreUpdateService:
    def __init__(self):
        self.status = "updateAvailable"

    def get(self):
        return self._snapshot()

    def check(self):
        self.status = "checking"
        return self._snapshot()

    def apply(self):
        self.status = "starting"
        return self._snapshot()

    def _snapshot(self):
        commit = CoreCommitSnapshot(
            sha1="b6501dff9",
            author="midolii",
            committed_at="2026-08-20 12:00:00 +0800",
            message="feat(api): 增加配置与实例操作接口",
        )
        return CoreUpdateSnapshot(
            status=self.status,
            available=self.status == "updateAvailable",
            enabled=True,
            source_repository="git@github.com:midolii/AzurPilot.git",
            source_branch="api-main",
            local_commit=commit,
            upstream_commit=commit,
            history=(commit,),
        )


class TestApiRoutes(unittest.TestCase):
    def setUp(self):
        facade = FakeFacade()
        api = create_api_app(
            facade=facade,
            instance_service=InstanceService(facade),
            config_read_service=FakeConfigReadService(),
            config_mutation_service=FakeConfigMutationService(),
            instance_control_service=FakeInstanceControlService(),
            task_read_service=FakeTaskReadService(),
            log_read_service=FakeLogReadService(),
            core_update_service=FakeCoreUpdateService(),
        )
        application = Starlette()
        application.mount("/api/v1", api)
        self.client = TestClient(application)

    def test_health(self):
        response = self.client.get("/api/v1/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok", "apiVersion": "0.5.0"}, response.json())

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
                "instanceConfigWrite",
                "instanceLifecycle",
                "instanceTasks",
                "instanceTaskRunNow",
                "instanceLogs",
                "instanceLogStream",
                "instanceLiveScreenshot",
                "coreUpdate",
            ],
            response.json()["capabilities"],
        )

    def test_core_update_routes(self):
        snapshot = self.client.get("/api/v1/updates/core")
        checking = self.client.post("/api/v1/updates/core/check")
        applying = self.client.post("/api/v1/updates/core/apply")

        self.assertEqual(200, snapshot.status_code)
        self.assertEqual("api-main", snapshot.json()["sourceBranch"])
        self.assertEqual("b6501dff9", snapshot.json()["history"][0]["sha1"])
        self.assertEqual("checking", checking.json()["status"])
        self.assertEqual(202, applying.status_code)
        self.assertEqual("starting", applying.json()["status"])

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

    def test_get_live_screenshot_stream(self):
        response = self.client.get("/api/v1/instances/alas/live-screenshot")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "instance": "alas",
                "transport": "websocket",
                "path": "/ws/live_screenshot",
                "codec": "h264",
                "modes": ["auto", "scrcpy", "screenshot"],
                "defaultMode": "auto",
                "defaultFps": 60,
                "defaultWidth": 640,
                "defaultBitrateScale": 1.0,
            },
            response.json(),
        )

    def test_unknown_instance_returns_stable_error(self):
        response = self.client.get("/api/v1/instances/missing")

        self.assertEqual(404, response.status_code)
        self.assertEqual("instance_not_found", response.json()["error"]["code"])

    def test_get_instance_config(self):
        response = self.client.get("/api/v1/instances/alas/config")

        self.assertEqual(200, response.status_code)
        self.assertIsNone(response.json()["values"]["Alas"]["Error"]["LlmApiKey"])
        self.assertEqual(["Alas.Error.LlmApiKey"], response.json()["redactedPaths"])
        self.assertEqual("a" * 64, response.json()["revision"])

    def test_patch_instance_config(self):
        response = self.client.patch(
            "/api/v1/instances/alas/config",
            json={
                "expectedRevision": "a" * 64,
                "changes": [{"path": "Main.Campaign.Name", "value": "13-4"}],
            },
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("13-4", response.json()["values"]["Main.Campaign.Name"])
        self.assertEqual("c" * 64, response.json()["revision"])

    def test_patch_instance_config_rejects_invalid_body_and_stale_revision(self):
        invalid = self.client.patch(
            "/api/v1/instances/alas/config", json={"changes": []}
        )
        stale = self.client.patch(
            "/api/v1/instances/alas/config",
            json={
                "expectedRevision": "b" * 64,
                "changes": [{"path": "Main.Campaign.Name", "value": "13-4"}],
            },
        )

        self.assertEqual(400, invalid.status_code)
        self.assertEqual("invalid_request", invalid.json()["error"]["code"])
        self.assertEqual(409, stale.status_code)
        self.assertEqual("config_revision_conflict", stale.json()["error"]["code"])

    def test_start_and_stop_instance(self):
        started = self.client.post("/api/v1/instances/alas/start")
        stopped = self.client.post("/api/v1/instances/alas/stop")

        self.assertEqual(200, started.status_code)
        self.assertTrue(started.json()["instance"]["running"])
        self.assertEqual("start", started.json()["action"])
        self.assertEqual(200, stopped.status_code)
        self.assertFalse(stopped.json()["instance"]["running"])

    def test_run_task_now(self):
        response = self.client.post("/api/v1/instances/alas/tasks/Main/run-now")

        self.assertEqual(200, response.status_code)
        self.assertEqual("runNow", response.json()["action"])
        self.assertEqual("2026-08-20T12:00:00", response.json()["scheduledAt"])

    def test_get_instance_config_schema(self):
        response = self.client.get("/api/v1/instances/alas/config/schema?lang=zh-CN")

        self.assertEqual(200, response.status_code)
        self.assertEqual("zh-CN", response.json()["language"])
        self.assertEqual(
            "Main.Campaign.Name",
            response.json()["menus"][0]["tasks"][0]["groups"][0]["fields"][0]["key"],
        )

    def test_get_instance_tasks(self):
        response = self.client.get("/api/v1/instances/alas/tasks")

        self.assertEqual(200, response.status_code)
        self.assertEqual("running", response.json()["running"][0]["state"])
        self.assertEqual(
            "2026-08-17T12:00:00", response.json()["running"][0]["nextRun"]
        )

    def test_get_instance_logs(self):
        response = self.client.get("/api/v1/instances/alas/logs?limit=20&format=ansi")

        self.assertEqual(200, response.status_code)
        self.assertEqual(["line"], response.json()["lines"])
        self.assertEqual("memory", response.json()["source"])
        self.assertEqual("ansi", response.json()["format"])
        self.assertEqual(
            1_777_000_000_123, response.json()["entries"][0]["timestampMs"]
        )

    def test_serialize_instance_log_stream_event(self):
        snapshot = FakeLogReadService().get("alas", limit=20, output_format="ansi")
        event = _serialize_log_event(
            LogTailResponse.model_validate(snapshot), retry=2_000
        )

        self.assertTrue(event.startswith("retry: 2000\nevent: logs\ndata: "))
        self.assertIn('"timestampMs":1777000000123', event)
        self.assertIn('"format":"ansi"', event)
        self.assertTrue(event.endswith("\n\n"))

    def test_invalid_language_returns_stable_error(self):
        response = self.client.get("/api/v1/instances/alas/config/schema?lang=invalid")

        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_language", response.json()["error"]["code"])

    def test_invalid_query_returns_stable_error(self):
        response = self.client.get("/api/v1/instances/alas/logs?limit=bad")
        stream_response = self.client.get(
            "/api/v1/instances/alas/logs/stream?limit=bad"
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_query", response.json()["error"]["code"])
        self.assertEqual(422, stream_response.status_code)
        self.assertEqual("invalid_query", stream_response.json()["error"]["code"])

    def test_data_read_error_does_not_expose_details(self):
        response = self.client.get("/api/v1/instances/broken/config")

        self.assertEqual(500, response.status_code)
        self.assertEqual("data_read_failed", response.json()["error"]["code"])
        self.assertNotIn("config", response.json()["error"]["message"])

    def test_new_routes_reject_unknown_instance(self):
        paths = (
            "/api/v1/instances/missing/config",
            "/api/v1/instances/missing/config/schema",
            "/api/v1/instances/missing/tasks",
            "/api/v1/instances/missing/logs",
            "/api/v1/instances/missing/logs/stream",
            "/api/v1/instances/missing/live-screenshot",
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(404, response.status_code)
                self.assertEqual("instance_not_found", response.json()["error"]["code"])

    def test_instance_data_routes_use_threadpool(self):
        async_mock = AsyncMock(side_effect=lambda function, *args: function(*args))
        with patch(
            "module.extension_api.webapi.routes.instance_data.run_in_threadpool",
            async_mock,
        ):
            response = self.client.get("/api/v1/instances/alas/config")

        self.assertEqual(200, response.status_code)
        async_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
