"""实例配置、生命周期和任务操作路由。"""

from json import JSONDecodeError

from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from module.extension_api.errors import InvalidRequestError
from module.extension_api.types import ConfigChange
from module.extension_api.webapi.models import (
    ConfigPatchRequest,
    ConfigResponse,
    InstanceActionResponse,
    TaskActionResponse,
)
from module.extension_api.webapi.responses import model_response


async def patch_instance_config(request: Request) -> JSONResponse:
    payload = await _parse_config_patch(request)
    snapshot = await run_in_threadpool(
        request.app.state.config_mutation_service.patch,
        request.path_params["instance"],
        payload.expected_revision,
        tuple(
            ConfigChange(path=change.path, value=change.value)
            for change in payload.changes
        ),
    )
    return model_response(ConfigResponse.model_validate(snapshot))


async def start_instance(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.instance_control_service.start,
        request.path_params["instance"],
    )
    return model_response(InstanceActionResponse.model_validate(snapshot))


async def stop_instance(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.instance_control_service.stop,
        request.path_params["instance"],
    )
    return model_response(InstanceActionResponse.model_validate(snapshot))


async def run_task_now(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.config_mutation_service.run_task_now,
        request.path_params["instance"],
        request.path_params["task"],
    )
    return model_response(TaskActionResponse.model_validate(snapshot))


async def _parse_config_patch(request: Request) -> ConfigPatchRequest:
    try:
        return ConfigPatchRequest.model_validate(await request.json())
    except (JSONDecodeError, TypeError, UnicodeDecodeError, ValidationError) as exc:
        raise InvalidRequestError("配置请求体无效") from exc
