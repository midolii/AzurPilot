import unittest
from types import SimpleNamespace

from starlette.applications import Starlette
from starlette.testclient import TestClient

from module.extension_api.services.instance_service import InstanceService
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


class TestApiRoutes(unittest.TestCase):
    def setUp(self):
        facade = FakeFacade()
        api = create_api_app(
            facade=facade,
            instance_service=InstanceService(facade),
        )
        application = Starlette()
        application.mount("/api/v1", api)
        self.client = TestClient(application)

    def test_health(self):
        response = self.client.get("/api/v1/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual({"status": "ok", "apiVersion": "0.1.0"}, response.json())

    def test_system(self):
        response = self.client.get("/api/v1/system")

        self.assertEqual(200, response.status_code)
        self.assertEqual("857deff50", response.json()["coreCommit"])
        self.assertEqual("3.14.6", response.json()["pythonVersion"])
        self.assertEqual(["instances"], response.json()["capabilities"])

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


if __name__ == "__main__":
    unittest.main()
