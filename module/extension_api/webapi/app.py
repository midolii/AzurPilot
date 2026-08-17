"""独立 API 子应用工厂。"""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import InstanceNotFoundError
from module.extension_api.services.instance_service import InstanceService
from module.extension_api.webapi.models import ErrorDetail, ErrorResponse
from module.extension_api.webapi.responses import model_response
from module.extension_api.webapi.routes.instances import get_instance, list_instances
from module.extension_api.webapi.routes.system import health, system


async def _instance_not_found(
    _request: Request, exc: InstanceNotFoundError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(code="instance_not_found", message=str(exc))
        ),
        status_code=404,
    )


def create_api_app(
    facade: CoreFacade | None = None,
    instance_service: InstanceService | None = None,
) -> Starlette:
    """创建挂载在 ``/api/v1`` 下的无状态传输层。"""
    facade = facade or CoreFacade()
    instance_service = instance_service or InstanceService(facade)
    application = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/system", system, methods=["GET"]),
            Route("/instances", list_instances, methods=["GET"]),
            Route("/instances/{instance:str}", get_instance, methods=["GET"]),
        ],
        exception_handlers={InstanceNotFoundError: _instance_not_found},
    )
    application.state.core_facade = facade
    application.state.instance_service = instance_service
    return application
