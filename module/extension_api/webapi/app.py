"""独立 API 子应用工厂。"""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import (
    DataReadError,
    InstanceNotFoundError,
    InvalidLanguageError,
    InvalidQueryError,
)
from module.extension_api.sensitive import SensitiveValuePolicy
from module.extension_api.services.config_read_service import ConfigReadService
from module.extension_api.services.instance_service import InstanceService
from module.extension_api.services.log_read_service import LogReadService
from module.extension_api.services.task_read_service import TaskReadService
from module.extension_api.webapi.models import ErrorDetail, ErrorResponse
from module.extension_api.webapi.responses import model_response
from module.extension_api.webapi.routes.instance_data import (
    get_instance_config,
    get_instance_config_schema,
    get_instance_logs,
    get_instance_tasks,
)
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


async def _invalid_language(
    _request: Request, _exc: InvalidLanguageError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code="invalid_language",
                message="不支持的配置语言",
            )
        ),
        status_code=422,
    )


async def _invalid_query(
    _request: Request, exc: InvalidQueryError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code="invalid_query",
                message=f"查询参数无效: {exc.parameter}",
            )
        ),
        status_code=422,
    )


async def _data_read_failed(
    _request: Request, _exc: DataReadError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code="data_read_failed",
                message="实例数据读取失败",
            )
        ),
        status_code=500,
    )


def create_api_app(
    facade: CoreFacade | None = None,
    instance_service: InstanceService | None = None,
    config_read_service: ConfigReadService | None = None,
    task_read_service: TaskReadService | None = None,
    log_read_service: LogReadService | None = None,
) -> Starlette:
    """创建挂载在 ``/api/v1`` 下的无状态传输层。"""
    facade = facade or CoreFacade()
    instance_service = instance_service or InstanceService(facade)
    sensitive_policy = SensitiveValuePolicy()
    config_read_service = config_read_service or ConfigReadService(
        facade, sensitive_policy
    )
    task_read_service = task_read_service or TaskReadService(facade)
    log_read_service = log_read_service or LogReadService(facade, sensitive_policy)
    application = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/system", system, methods=["GET"]),
            Route("/instances", list_instances, methods=["GET"]),
            Route(
                "/instances/{instance:str}/config/schema",
                get_instance_config_schema,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/config",
                get_instance_config,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/tasks",
                get_instance_tasks,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/logs",
                get_instance_logs,
                methods=["GET"],
            ),
            Route("/instances/{instance:str}", get_instance, methods=["GET"]),
        ],
        exception_handlers={
            InstanceNotFoundError: _instance_not_found,
            InvalidLanguageError: _invalid_language,
            InvalidQueryError: _invalid_query,
            DataReadError: _data_read_failed,
        },
    )
    application.state.core_facade = facade
    application.state.instance_service = instance_service
    application.state.config_read_service = config_read_service
    application.state.task_read_service = task_read_service
    application.state.log_read_service = log_read_service
    return application
