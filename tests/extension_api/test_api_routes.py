import sys
import unittest
from datetime import datetime
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.applications import Starlette
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from module.extension_api.auth import AuthService
from module.extension_api.errors import (
    ConfigRevisionConflictError,
    DataReadError,
    InstanceNotFoundError,
    InvalidLanguageError,
    InvalidQueryError,
)
from module.extension_api.services.instance_service import InstanceService
from module.extension_api.types import (
    CommissionPageSnapshot,
    CommissionPeriodSummarySnapshot,
    CommissionRecordSnapshot,
    CommissionRetentionSnapshot,
    CommissionRewardSnapshot,
    CommissionSummaryItemSnapshot,
    CommissionSummarySnapshot,
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
    ResourcePointSnapshot,
    ResourceTimelineSnapshot,
    TaskActionSnapshot,
    TaskListSnapshot,
    TaskSnapshot,
)
from module.extension_api.webapi import create_api_app
from module.extension_api.webapi.models import (
    InstanceListResponse,
    InstanceResponse,
    LogTailResponse,
    TaskListResponse,
)
from module.extension_api.webapi.routes.instance_data import (
    _serialize_log_event,
    _serialize_task_event,
)
from module.extension_api.webapi.routes.instances import _serialize_instance_event


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


class FakeStatisticsReadService:
    def get_resources(self, instance, limit=None, period=None):
        if instance == "missing":
            raise InstanceNotFoundError(instance)
        if limit == "bad":
            raise InvalidQueryError("limit")
        if period == "bad":
            raise InvalidQueryError("period")
        point = ResourcePointSnapshot(
            timestamp_ms=1_777_000_000_123,
            oil=12_000,
            coin=34_000,
            gem=500,
            pt=1200,
            cube=80,
            core=200,
            medal=30,
            merit=400,
            guild_coin=600,
            action_point=1380,
            action_point_box=1200,
            yellow_coin=700,
            purple_coin=90,
        )
        return ResourceTimelineSnapshot(
            instance=instance,
            period=period or "month",
            items=(point,),
            count=1,
            total_count=1,
            limit=int(limit or 500),
            sampled=False,
            available_from_ms=point.timestamp_ms,
            available_to_ms=point.timestamp_ms,
        )

    def get_commission_summary(self, instance):
        if instance == "missing":
            raise InstanceNotFoundError(instance)
        item = CommissionSummaryItemSnapshot(key="cube", total=4, count=2, average=2.0)
        return CommissionSummarySnapshot(
            instance=instance,
            periods=(
                CommissionPeriodSummarySnapshot(
                    period="day",
                    starts_at_ms=1_777_000_000_000,
                    total_commissions=4,
                    items=(item,),
                ),
            ),
        )

    def get_commissions(self, instance, page=None, page_size=None):
        if instance == "missing":
            raise InstanceNotFoundError(instance)
        if page == "bad":
            raise InvalidQueryError("page")
        record = CommissionRecordSnapshot(
            timestamp_ms=1_777_000_000_123,
            commission_count=4,
            rewards=(CommissionRewardSnapshot(key="cube", amount=2),),
        )
        return CommissionPageSnapshot(
            instance=instance,
            items=(record,),
            page=int(page or 1),
            page_size=int(page_size or 20),
            total=1,
            total_pages=1,
            retention=CommissionRetentionSnapshot(
                available_from_ms=record.timestamp_ms,
                available_to_ms=record.timestamp_ms,
                retained_months=1,
                max_entries_per_month=5000,
                automatic_month_cleanup=False,
            ),
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
        self.auth_directory = TemporaryDirectory()
        self.addCleanup(self.auth_directory.cleanup)
        auth_root = self.auth_directory.name
        auth_service = AuthService(
            database_path=f"{auth_root}/auth.db",
            bootstrap_path=f"{auth_root}/bootstrap.txt",
            password_reset_path=f"{auth_root}/password-reset.json",
        )
        self.auth_service = auth_service
        facade = FakeFacade()
        api = create_api_app(
            facade=facade,
            instance_service=InstanceService(facade),
            config_read_service=FakeConfigReadService(),
            config_mutation_service=FakeConfigMutationService(),
            instance_control_service=FakeInstanceControlService(),
            task_read_service=FakeTaskReadService(),
            log_read_service=FakeLogReadService(),
            statistics_read_service=FakeStatisticsReadService(),
            core_update_service=FakeCoreUpdateService(),
            auth_service=auth_service,
        )
        application = Starlette()
        application.mount("/api/v1", api)
        self.client = TestClient(application)
        setup = self.client.post(
            "/api/v1/auth/setup",
            json={
                "bootstrapToken": auth_service.read_bootstrap_token(),
                "username": "test-owner",
                "password": "test-password-strong",
            },
        )
        self.assertEqual(201, setup.status_code, setup.text)

    def test_authenticated_websocket_adapter_consumes_single_use_ticket(self):
        ticket_response = self.client.post(
            "/api/v1/auth/ws-tickets",
            json={"purpose": "live_screenshot", "instance": "alas"},
        )
        self.assertEqual(201, ticket_response.status_code, ticket_response.text)
        ticket = ticket_response.json()["ticket"]

        fake_api = ModuleType("module.webui.api")

        async def fake_live_screenshot(websocket):
            await websocket.accept()
            principal = websocket.scope["auth_principal"]
            await websocket.send_json(
                {"authType": principal.auth_type, "username": principal.username}
            )
            await websocket.close()

        fake_api.ws_live_screenshot = fake_live_screenshot
        with patch.dict(sys.modules, {"module.webui.api": fake_api}):
            with self.client.websocket_connect(
                f"/api/v1/ws/live_screenshot?instance=alas&ticket={ticket}"
            ) as websocket:
                self.assertEqual(
                    {"authType": "websocket_ticket", "username": "test-owner"},
                    websocket.receive_json(),
                )

            with (
                self.assertRaises(WebSocketDisconnect) as rejected,
                self.client.websocket_connect(
                    f"/api/v1/ws/live_screenshot?instance=alas&ticket={ticket}"
                ),
            ):
                pass

        self.assertEqual(4401, rejected.exception.code)

    def test_health(self):
        response = self.client.get("/api/v1/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok", "apiVersion": "1.0.0"}, response.json())

    def test_system(self):
        response = self.client.get("/api/v1/system")

        self.assertEqual(200, response.status_code)
        self.assertEqual("857deff50", response.json()["coreCommit"])
        self.assertEqual("3.14.6", response.json()["pythonVersion"])
        self.assertEqual(
            [
                "authentication",
                "clientTokens",
                "authenticatedWebSocket",
                "instances",
                "instanceStream",
                "instanceConfig",
                "instanceConfigSchema",
                "instanceConfigWrite",
                "instanceLifecycle",
                "instanceTasks",
                "instanceTaskStream",
                "instanceTaskRunNow",
                "instanceLogs",
                "instanceLogStream",
                "instanceResourceStatistics",
                "instanceCommissionHistory",
                "instanceCommissionSummary",
                "instanceLiveScreenshot",
                "instanceLiveControl",
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

    def test_auth_session_and_client_token_scope(self):
        session = self.client.get("/api/v1/auth/session")
        created = self.client.post(
            "/api/v1/auth/tokens",
            json={"name": "只读系统检查", "scopes": ["system:read"]},
        )

        self.assertTrue(session.json()["authenticated"])
        self.assertEqual("no-store", session.headers["cache-control"])
        self.assertEqual("test-owner", session.json()["user"]["username"])
        self.assertEqual(201, created.status_code)
        token = created.json()["token"]

        isolated_client = TestClient(self.client.app)
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(
            200,
            isolated_client.get("/api/v1/system", headers=headers).status_code,
        )
        denied = isolated_client.get("/api/v1/instances", headers=headers)
        self.assertEqual(403, denied.status_code)
        self.assertEqual("permission_denied", denied.json()["error"]["code"])

    def test_cookie_mutation_rejects_cross_origin_requests(self):
        response = self.client.post(
            "/api/v1/updates/core/check",
            headers={"Origin": "https://attacker.example"},
        )

        self.assertEqual(403, response.status_code)
        self.assertEqual("permission_denied", response.json()["error"]["code"])

    def test_https_proxy_marks_session_cookie_secure(self):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "test-owner", "password": "test-password-strong"},
            headers={"X-Forwarded-Proto": "https"},
        )

        self.assertEqual(200, response.status_code)
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Secure", cookie)

    def test_logout_invalidates_session(self):
        response = self.client.post("/api/v1/auth/logout")
        denied = self.client.get("/api/v1/system")

        self.assertEqual(204, response.status_code)
        self.assertEqual(401, denied.status_code)
        self.assertEqual("authentication_required", denied.json()["error"]["code"])

    def test_password_reset_uses_local_token_and_creates_session(self):
        challenge = self.auth_service.request_password_reset()
        status = self.client.get("/api/v1/auth/status")
        isolated_client = TestClient(self.client.app)
        reset = isolated_client.post(
            "/api/v1/auth/password-reset",
            json={
                "resetToken": challenge.token,
                "password": "replacement-password-strong",
            },
        )

        self.assertTrue(status.json()["passwordResetAvailable"])
        self.assertEqual(200, reset.status_code, reset.text)
        self.assertTrue(reset.json()["authenticated"])
        self.assertIn("azurpilot_session=", reset.headers["set-cookie"])
        self.assertFalse(self.auth_service.password_reset_available)

    def test_password_reset_rejects_unknown_token(self):
        isolated_client = TestClient(self.client.app)
        response = isolated_client.post(
            "/api/v1/auth/password-reset",
            json={
                "resetToken": "invalid-password-reset-token",
                "password": "replacement-password-strong",
            },
        )

        self.assertEqual(403, response.status_code)
        self.assertEqual(
            "password_reset_token_invalid", response.json()["error"]["code"]
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

    def test_get_live_screenshot_stream(self):
        response = self.client.get("/api/v1/instances/alas/live-screenshot")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "instance": "alas",
                "transport": "websocket",
                "path": "/api/v1/ws/live_screenshot",
                "codec": "h264",
                "modes": ["auto", "scrcpy", "screenshot"],
                "defaultMode": "auto",
                "defaultFps": 60,
                "defaultWidth": 640,
                "defaultBitrateScale": 1.0,
                "control": {
                    "transport": "websocket",
                    "path": "/api/v1/ws/live_control",
                    "protocolVersion": 2,
                    "coordinateSpace": {"width": 1280, "height": 720},
                    "actions": [
                        "tap",
                        "drag",
                        "touch",
                        "key",
                        "text",
                        "back",
                        "home",
                        "app_switch",
                    ],
                },
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

    def test_get_resource_statistics(self):
        response = self.client.get(
            "/api/v1/instances/alas/statistics/resources?limit=200&period=week"
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(200, response.json()["limit"])
        self.assertEqual("week", response.json()["period"])
        self.assertEqual(1, response.json()["totalCount"])
        self.assertFalse(response.json()["sampled"])
        self.assertEqual(12_000, response.json()["items"][0]["oil"])
        self.assertEqual(1380, response.json()["items"][0]["actionPoint"])
        self.assertEqual(1200, response.json()["items"][0]["actionPointBox"])
        self.assertEqual(1_777_000_000_123, response.json()["items"][0]["timestampMs"])

    def test_get_paginated_commission_statistics(self):
        response = self.client.get(
            "/api/v1/instances/alas/statistics/commissions?page=1&pageSize=20"
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.json()["page"])
        self.assertEqual(20, response.json()["pageSize"])
        self.assertEqual(1, response.json()["totalPages"])
        self.assertEqual("cube", response.json()["items"][0]["rewards"][0]["key"])
        self.assertEqual(5000, response.json()["retention"]["maxEntriesPerMonth"])
        self.assertFalse(response.json()["retention"]["automaticMonthCleanup"])

    def test_get_commission_summary(self):
        response = self.client.get(
            "/api/v1/instances/alas/statistics/commissions/summary"
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual("day", response.json()["periods"][0]["period"])
        self.assertEqual(4, response.json()["periods"][0]["totalCommissions"])
        self.assertEqual(2.0, response.json()["periods"][0]["items"][0]["average"])

    def test_serialize_instance_log_stream_event(self):
        snapshot = FakeLogReadService().get("alas", limit=20, output_format="ansi")
        event = _serialize_log_event(
            LogTailResponse.model_validate(snapshot), retry=2_000
        )

        self.assertTrue(event.startswith("retry: 2000\nevent: logs\ndata: "))
        self.assertIn('"timestampMs":1777000000123', event)
        self.assertIn('"format":"ansi"', event)
        self.assertTrue(event.endswith("\n\n"))

    def test_serialize_task_stream_event(self):
        snapshot = FakeTaskReadService().get("alas")
        event = _serialize_task_event(
            TaskListResponse.model_validate(snapshot), retry=1_000
        )

        self.assertTrue(event.startswith("retry: 1000\nevent: tasks\ndata: "))
        self.assertIn('"instance":"alas"', event)
        self.assertIn('"state":"running"', event)

    def test_serialize_instance_stream_event(self):
        snapshots = InstanceService(FakeFacade()).list()
        response = InstanceListResponse(
            items=[InstanceResponse.model_validate(snapshot) for snapshot in snapshots]
        )
        event = _serialize_instance_event(response, retry=1_000)

        self.assertTrue(event.startswith("retry: 1000\nevent: instances\ndata: "))
        self.assertIn('"name":"alas"', event)
        self.assertIn('"running":true', event)

    def test_invalid_language_returns_stable_error(self):
        response = self.client.get("/api/v1/instances/alas/config/schema?lang=invalid")

        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_language", response.json()["error"]["code"])

    def test_invalid_query_returns_stable_error(self):
        response = self.client.get("/api/v1/instances/alas/logs?limit=bad")
        stream_response = self.client.get(
            "/api/v1/instances/alas/logs/stream?limit=bad"
        )
        resource_response = self.client.get(
            "/api/v1/instances/alas/statistics/resources?limit=bad"
        )
        resource_period_response = self.client.get(
            "/api/v1/instances/alas/statistics/resources?period=bad"
        )
        commission_response = self.client.get(
            "/api/v1/instances/alas/statistics/commissions?page=bad"
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("invalid_query", response.json()["error"]["code"])
        self.assertEqual(422, stream_response.status_code)
        self.assertEqual("invalid_query", stream_response.json()["error"]["code"])
        self.assertEqual(422, resource_response.status_code)
        self.assertEqual("invalid_query", resource_response.json()["error"]["code"])
        self.assertEqual(422, resource_period_response.status_code)
        self.assertEqual(
            "invalid_query", resource_period_response.json()["error"]["code"]
        )
        self.assertEqual(422, commission_response.status_code)
        self.assertEqual("invalid_query", commission_response.json()["error"]["code"])

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
            "/api/v1/instances/missing/tasks/stream",
            "/api/v1/instances/missing/logs",
            "/api/v1/instances/missing/logs/stream",
            "/api/v1/instances/missing/statistics/resources",
            "/api/v1/instances/missing/statistics/commissions",
            "/api/v1/instances/missing/statistics/commissions/summary",
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
