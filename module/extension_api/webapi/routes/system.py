"""系统信息路由。"""

from starlette.requests import Request
from starlette.responses import JSONResponse

from module.extension_api import API_VERSION
from module.extension_api.webapi.models import HealthResponse, SystemResponse
from module.extension_api.webapi.responses import model_response


async def health(_request: Request) -> JSONResponse:
    return model_response(HealthResponse(api_version=API_VERSION))


async def system(request: Request) -> JSONResponse:
    facade = request.app.state.core_facade
    return model_response(
        SystemResponse(
            api_version=API_VERSION,
            core_commit=facade.get_core_commit(),
            python_version=facade.get_python_version(),
            platform=facade.get_platform(),
            capabilities=["instances"],
        )
    )
