"""实例统计数据只读路由。"""

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from module.extension_api.webapi.models import (
    CommissionPageResponse,
    ResourceTimelineResponse,
)
from module.extension_api.webapi.responses import model_response


async def get_resource_statistics(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.statistics_read_service.get_resources,
        request.path_params["instance"],
        request.query_params.get("limit"),
    )
    return model_response(ResourceTimelineResponse.model_validate(snapshot))


async def get_commission_statistics(request: Request) -> JSONResponse:
    snapshot = await run_in_threadpool(
        request.app.state.statistics_read_service.get_commissions,
        request.path_params["instance"],
        request.query_params.get("page"),
        request.query_params.get("pageSize"),
    )
    return model_response(CommissionPageResponse.model_validate(snapshot))
