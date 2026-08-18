"""实例配置、任务和日志只读路由。"""

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from module.extension_api.webapi.models import (
    ConfigResponse,
    ConfigSchemaResponse,
    LogTailResponse,
    TaskListResponse,
)
from module.extension_api.webapi.responses import model_response


async def get_instance_config(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.config_read_service.get_config,
        request.path_params["instance"],
    )
    return model_response(ConfigResponse.model_validate(snapshot))


async def get_instance_config_schema(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.config_read_service.get_schema,
        request.path_params["instance"],
        request.query_params.get("lang"),
    )
    return model_response(ConfigSchemaResponse.model_validate(snapshot))


async def get_instance_tasks(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.task_read_service.get,
        request.path_params["instance"],
    )
    return model_response(TaskListResponse.model_validate(snapshot))


async def get_instance_logs(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.log_read_service.get,
        request.path_params["instance"],
        request.query_params.get("limit"),
        request.query_params.get("format"),
    )
    return model_response(LogTailResponse.model_validate(snapshot))
