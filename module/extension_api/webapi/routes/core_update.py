"""AzurPilot 核心更新路由。"""

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from module.extension_api.webapi.models import CoreUpdateResponse
from module.extension_api.webapi.responses import model_response


async def get_core_update(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(request.app.state.core_update_service.get)
    return model_response(CoreUpdateResponse.model_validate(snapshot))


async def check_core_update(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(request.app.state.core_update_service.check)
    return model_response(CoreUpdateResponse.model_validate(snapshot))


async def apply_core_update(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(request.app.state.core_update_service.apply)
    return model_response(CoreUpdateResponse.model_validate(snapshot), status_code=202)
