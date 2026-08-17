"""实例查询路由。"""

from starlette.requests import Request
from starlette.responses import JSONResponse

from module.extension_api.webapi.models import (
    InstanceListResponse,
    InstanceResponse,
)
from module.extension_api.webapi.responses import model_response


async def list_instances(request: Request) -> JSONResponse:
    snapshots = request.app.state.instance_service.list()
    return model_response(
        InstanceListResponse(
            items=[InstanceResponse.model_validate(item) for item in snapshots]
        )
    )


async def get_instance(request: Request) -> JSONResponse:
    snapshot = request.app.state.instance_service.get(
        request.path_params["instance"]
    )
    return model_response(InstanceResponse.model_validate(snapshot))
