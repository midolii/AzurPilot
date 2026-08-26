"""独立 API 子应用工厂。"""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute

from module.logger import logger
from module.extension_api.auth import (
    AuthenticationRequiredError,
    AuthService,
    BootstrapTokenError,
    PasswordResetTokenError,
    PermissionDeniedError,
    RateLimitExceededError,
    SetupAlreadyCompletedError,
    SetupRequiredError,
    ValidationError,
)
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
from module.extension_api.webapi.auth import optional_auth, protected
from module.extension_api.webapi.models import ErrorDetail, ErrorResponse
from module.extension_api.webapi.responses import model_response
from module.extension_api.webapi.routes.auth import (
    create_client_token,
    create_websocket_ticket,
    get_auth_status,
    get_session,
    list_client_tokens,
    login,
    logout,
    revoke_client_token,
    reset_password,
    setup_auth,
)
from module.extension_api.webapi.routes.authenticated_websocket import (
    live_control_websocket,
    live_screenshot_websocket,
)
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


async def _setup_required(_request: Request, exc: SetupRequiredError) -> JSONResponse:
    return model_response(
        ErrorResponse(error=ErrorDetail(code="setup_required", message=str(exc))),
        status_code=503,
    )


async def _authentication_required(
    _request: Request, exc: AuthenticationRequiredError
) -> JSONResponse:
    response = model_response(
        ErrorResponse(
            error=ErrorDetail(code="authentication_required", message=str(exc))
        ),
        status_code=401,
    )
    response.headers["WWW-Authenticate"] = "Bearer"
    return response


async def _permission_denied(
    request: Request, exc: PermissionDeniedError
) -> JSONResponse:
    logger.warning(
        f"[API] 拒绝请求 {request.method} {request.url.path}: {exc}"
    )
    return model_response(
        ErrorResponse(
            error=ErrorDetail(
                code="permission_denied",
                message="请求未获授权",
            )
        ),
        status_code=403,
    )


async def _bootstrap_token_invalid(
    _request: Request, exc: BootstrapTokenError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(code="bootstrap_token_invalid", message=str(exc))
        ),
        status_code=403,
    )


async def _password_reset_token_invalid(
    _request: Request, exc: PasswordResetTokenError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(code="password_reset_token_invalid", message=str(exc))
        ),
        status_code=403,
    )


async def _setup_already_completed(
    _request: Request, exc: SetupAlreadyCompletedError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(code="setup_already_completed", message=str(exc))
        ),
        status_code=409,
    )


async def _rate_limited(_request: Request, exc: RateLimitExceededError) -> JSONResponse:
    response = model_response(
        ErrorResponse(error=ErrorDetail(code="rate_limited", message=str(exc))),
        status_code=429,
    )
    response.headers["Retry-After"] = "60"
    return response


async def _auth_validation_failed(
    _request: Request, exc: ValidationError
) -> JSONResponse:
    return model_response(
        ErrorResponse(
            error=ErrorDetail(code="auth_validation_failed", message=str(exc))
        ),
        status_code=422,
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
    auth_service: AuthService | None = None,
) -> Starlette:
    """创建挂载在 ``/api/v1`` 下的扩展 API 传输层。"""
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
    auth_service = auth_service or AuthService()
    application = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/auth/status", get_auth_status, methods=["GET"]),
            Route("/auth/setup", setup_auth, methods=["POST"]),
            Route("/auth/login", login, methods=["POST"]),
            Route("/auth/password-reset", reset_password, methods=["POST"]),
            Route("/auth/logout", logout, methods=["POST"]),
            Route("/auth/session", optional_auth(get_session), methods=["GET"]),
            Route(
                "/auth/tokens",
                protected(list_client_tokens, "tokens:manage"),
                methods=["GET"],
            ),
            Route(
                "/auth/tokens",
                protected(create_client_token, "tokens:manage"),
                methods=["POST"],
            ),
            Route(
                "/auth/tokens/{token_id:str}",
                protected(revoke_client_token, "tokens:manage"),
                methods=["DELETE"],
            ),
            Route(
                "/auth/ws-tickets",
                protected(create_websocket_ticket),
                methods=["POST"],
            ),
            WebSocketRoute("/ws/live_screenshot", live_screenshot_websocket),
            WebSocketRoute("/ws/live_control", live_control_websocket),
            Route("/system", protected(system, "system:read"), methods=["GET"]),
            Route(
                "/updates/core",
                protected(get_core_update, "system:read"),
                methods=["GET"],
            ),
            Route(
                "/updates/core/check",
                protected(check_core_update, "core:update"),
                methods=["POST"],
            ),
            Route(
                "/updates/core/apply",
                protected(apply_core_update, "core:update"),
                methods=["POST"],
            ),
            Route(
                "/instances/stream",
                protected(stream_instances, "instances:read"),
                methods=["GET"],
            ),
            Route(
                "/instances",
                protected(list_instances, "instances:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/config/schema",
                protected(get_instance_config_schema, "config:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/config",
                protected(get_instance_config, "config:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/config",
                protected(patch_instance_config, "config:write"),
                methods=["PATCH"],
            ),
            Route(
                "/instances/{instance:str}/tasks/stream",
                protected(get_instance_tasks_stream, "tasks:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/tasks",
                protected(get_instance_tasks, "tasks:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/tasks/{task:str}/run-now",
                protected(run_task_now, "tasks:run"),
                methods=["POST"],
            ),
            Route(
                "/instances/{instance:str}/start",
                protected(start_instance, "instances:operate"),
                methods=["POST"],
            ),
            Route(
                "/instances/{instance:str}/stop",
                protected(stop_instance, "instances:operate"),
                methods=["POST"],
            ),
            Route(
                "/instances/{instance:str}/logs/stream",
                protected(get_instance_logs_stream, "logs:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/logs",
                protected(get_instance_logs, "logs:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/statistics/resources",
                protected(get_resource_statistics, "statistics:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/statistics/commissions",
                protected(get_commission_statistics, "statistics:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/statistics/commissions/summary",
                protected(get_commission_summary, "statistics:read"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}/live-screenshot",
                protected(get_live_screenshot_stream, "media:view"),
                methods=["GET"],
            ),
            Route(
                "/instances/{instance:str}",
                protected(get_instance, "instances:read"),
                methods=["GET"],
            ),
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
            SetupRequiredError: _setup_required,
            AuthenticationRequiredError: _authentication_required,
            PermissionDeniedError: _permission_denied,
            BootstrapTokenError: _bootstrap_token_invalid,
            PasswordResetTokenError: _password_reset_token_invalid,
            SetupAlreadyCompletedError: _setup_already_completed,
            RateLimitExceededError: _rate_limited,
            ValidationError: _auth_validation_failed,
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
    application.state.auth_service = auth_service
    return application
