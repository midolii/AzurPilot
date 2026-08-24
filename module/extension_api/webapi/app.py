"""独立 API 子应用工厂。"""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import (
    ConfigRevisionConflictError,
    ConfigValidationError,
    CoreUpdateBusyError,
    CoreUpdateUnavailableError,
    DataReadError,
    DataWriteError,
    InstanceNotFoundError,
    InstanceOperationError,
    InvalidLanguageError,
    InvalidQueryError,
    InvalidRequestError,
    TaskDisabledError,
    TaskNotFoundError,
)
from module.extension_api.sensitive import SensitiveValuePolicy
from module.extension_api.services.config_mutation_service import ConfigMutationService
from module.extension_api.services.config_read_service import ConfigReadService
from module.extension_api.services.core_update_service import CoreUpdateService
from module.extension_api.services.instance_control_service import (
    InstanceControlService,
)
from module.extension_api.services.instance_service import InstanceService
from module.extension_api.services.log_read_service import LogReadService
from module.extension_api.services.statistics_read_service import StatisticsReadService
from module.extension_api.services.task_read_service import TaskReadService
from module.extension_api.webapi.models import ErrorDetail, ErrorResponse
from module.extension_api.webapi.responses import model_response
from module.extension_api.webapi.routes.core_update import (
    apply_core_update,
    check_core_update,
    get_core_update,
)
from module.extension_api.webapi.routes.instance_data import (
    get_instance_config,
    get_instance_config_schema,
    get_instance_logs,
    get_instance_logs_stream,
    get_instance_tasks,
    get_instance_tasks_stream,
)
from module.extension_api.webapi.routes.instance_mutations import (
    patch_instance_config,
    run_task_now,
    start_instance,
    stop_instance,
)
from module.extension_api.webapi.routes.instances import (
    get_instance,
    list_instances,
    stream_instances,
)
from module.extension_api.webapi.routes.live_screenshot import (
    get_live_screenshot_stream,
)
from module.extension_api.webapi.routes.statistics import (
    get_commission_statistics,
    get_commission_summary,
    get_resource_statistics,
)
from module.extension_api.webapi.routes.system import health, system


async def _instance_not_found(
    _request: Request, exc: InstanceNotFoundError
) -> JSONResponse:
    return model_response(
        ErrorResponse(error=ErrorDetail(code="instance_not_found", message=str(exc))),
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


async def _invalid_query(_request: Request, exc: InvalidQueryError) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code="invalid_query",
                message=f"查询参数无效: {exc.parameter}",
            )
        ),
        status_code=422,
    )


async def _data_read_failed(_request: Request, _exc: DataReadError) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code="data_read_failed",
                message="实例数据读取失败",
            )
        ),
        status_code=500,
    )


async def _invalid_request(_request: Request, exc: InvalidRequestError) -> JSONResponse:
    return model_response(
        ErrorResponse(error=ErrorDetail(code="invalid_request", message=str(exc))),
        status_code=400,
    )


async def _config_validation_failed(
    _request: Request, exc: ConfigValidationError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(code="config_validation_failed", message=str(exc))
        ),
        status_code=422,
    )


async def _config_revision_conflict(
    _request: Request, _exc: ConfigRevisionConflictError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code="config_revision_conflict",
                message="配置已被其他客户端更新，请刷新后重试",
            )
        ),
        status_code=409,
    )


async def _task_not_found(_request: Request, exc: TaskNotFoundError) -> JSONResponse:
    return model_response(
        ErrorResponse(error=ErrorDetail(code="task_not_found", message=str(exc))),
        status_code=404,
    )


async def _task_disabled(_request: Request, exc: TaskDisabledError) -> JSONResponse:
    return model_response(
        ErrorResponse(error=ErrorDetail(code="task_disabled", message=str(exc))),
        status_code=409,
    )


async def _instance_operation_failed(
    _request: Request, exc: InstanceOperationError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code=f"instance_{exc.action}_failed",
                message="实例操作未完成，请检查核心日志",
            )
        ),
        status_code=409,
    )


async def _data_write_failed(_request: Request, _exc: DataWriteError) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code="data_write_failed",
                message="实例数据写入失败",
            )
        ),
        status_code=500,
    )


async def _core_update_unavailable(
    _request: Request, exc: CoreUpdateUnavailableError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(code="core_update_unavailable", message=str(exc))
        ),
        status_code=409,
    )


async def _core_update_busy(
    _request: Request, exc: CoreUpdateBusyError
) -> JSONResponse:
    return model_response(
        ErrorResponse(error=ErrorDetail(code="core_update_busy", message=str(exc))),
        status_code=409,
    )


def create_api_app(
    facade: CoreFacade | None = None,
    instance_service: InstanceService | None = None,
    config_read_service: ConfigReadService | None = None,
    config_mutation_service: ConfigMutationService | None = None,
    instance_control_service: InstanceControlService | None = None,
    task_read_service: TaskReadService | None = None,
    log_read_service: LogReadService | None = None,
    statistics_read_service: StatisticsReadService | None = None,
    core_update_service: CoreUpdateService | None = None,
) -> Starlette:
    """创建挂载在 ``/api/v1`` 下的无状态传输层。"""
    facade = facade or CoreFacade()
    instance_service = instance_service or InstanceService(facade)
    sensitive_policy = SensitiveValuePolicy()
    config_read_service = config_read_service or ConfigReadService(
        facade, sensitive_policy
    )
    config_mutation_service = config_mutation_service or ConfigMutationService(
        facade, config_read_service
    )
    instance_control_service = instance_control_service or InstanceControlService(
        facade, instance_service
    )
    task_read_service = task_read_service or TaskReadService(facade)
    log_read_service = log_read_service or LogReadService(facade, sensitive_policy)
    statistics_read_service = statistics_read_service or StatisticsReadService(facade)
    core_update_service = core_update_service or CoreUpdateService()
    application = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/system", system, methods=["GET"]),
            Route("/updates/core", get_core_update, methods=["GET"]),
            Route("/updates/core/check", check_core_update, methods=["POST"]),
            Route("/updates/core/apply", apply_core_update, methods=["POST"]),
            Route("/instances/stream", stream_instances, methods=["GET"]),
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
                "/instances/{instance:str}/config",
                patch_instance_config,
                methods=["PATCH"],
            ),
            Route(
                "/instances/{instance:str}/tasks/stream",
                get_instance_tasks_stream,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/tasks",
                get_instance_tasks,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/tasks/{task:str}/run-now",
                run_task_now,
                methods=["POST"],
            ),
            Route(
                "/instances/{instance:str}/start",
                start_instance,
                methods=["POST"],
            ),
            Route(
                "/instances/{instance:str}/stop",
                stop_instance,
                methods=["POST"],
            ),
            Route(
                "/instances/{instance:str}/logs/stream",
                get_instance_logs_stream,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/logs",
                get_instance_logs,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/statistics/resources",
                get_resource_statistics,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/statistics/commissions",
                get_commission_statistics,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/statistics/commissions/summary",
                get_commission_summary,
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/live-screenshot",
                get_live_screenshot_stream,
                methods=["GET"],
            ),
            Route("/instances/{instance:str}", get_instance, methods=["GET"]),
        ],
        exception_handlers={
            InstanceNotFoundError: _instance_not_found,
            InvalidLanguageError: _invalid_language,
            InvalidQueryError: _invalid_query,
            DataReadError: _data_read_failed,
            InvalidRequestError: _invalid_request,
            ConfigValidationError: _config_validation_failed,
            ConfigRevisionConflictError: _config_revision_conflict,
            TaskNotFoundError: _task_not_found,
            TaskDisabledError: _task_disabled,
            InstanceOperationError: _instance_operation_failed,
            DataWriteError: _data_write_failed,
            CoreUpdateUnavailableError: _core_update_unavailable,
            CoreUpdateBusyError: _core_update_busy,
        },
    )
    application.state.core_facade = facade
    application.state.instance_service = instance_service
    application.state.config_read_service = config_read_service
    application.state.config_mutation_service = config_mutation_service
    application.state.instance_control_service = instance_control_service
    application.state.task_read_service = task_read_service
    application.state.log_read_service = log_read_service
    application.state.statistics_read_service = statistics_read_service
    application.state.core_update_service = core_update_service
    return application
