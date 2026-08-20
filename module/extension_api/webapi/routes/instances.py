"""实例查询与状态流路由。"""

import asyncio
from collections.abc import Iterable

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from module.extension_api.webapi.models import (
    InstanceListResponse,
    InstanceResponse,
)
from module.extension_api.webapi.responses import model_response
from module.extension_api.webapi.sse import (
    SSE_HEADERS,
    serialize_error_event,
    serialize_model_event,
)
from module.extension_api.types import InstanceSnapshot
from module.logger import logger

INSTANCE_STREAM_POLL_INTERVAL_SECONDS = 1.0
INSTANCE_STREAM_KEEPALIVE_SECONDS = 15.0


def _build_instance_list_response(
    snapshots: Iterable[InstanceSnapshot],
) -> InstanceListResponse:
    return InstanceListResponse(
        items=[InstanceResponse.model_validate(item) for item in snapshots]
    )


async def list_instances(request: Request) -> JSONResponse:
    snapshots = request.app.state.instance_service.list()
    return model_response(_build_instance_list_response(snapshots))


def _serialize_instance_event(
    response: InstanceListResponse, retry: int | None = None
) -> str:
    return serialize_model_event("instances", response, retry)


async def stream_instances(request: Request) -> StreamingResponse:
    """持续推送实例运行状态，避免客户端轮询整个实例列表。"""
    service = request.app.state.instance_service
    initial_snapshots = await run_in_threadpool(service.list)
    initial_response = _build_instance_list_response(initial_snapshots)
    initial_payload = _serialize_instance_event(initial_response, retry=1_000)

    async def event_generator():
        last_payload = _serialize_instance_event(initial_response)
        last_keepalive = asyncio.get_running_loop().time()
        yield initial_payload

        try:
            while True:
                await asyncio.sleep(INSTANCE_STREAM_POLL_INTERVAL_SECONDS)
                if await request.is_disconnected():
                    break

                snapshots = await run_in_threadpool(service.list)
                response = _build_instance_list_response(snapshots)
                payload = _serialize_instance_event(response)
                now = asyncio.get_running_loop().time()
                if payload != last_payload:
                    last_payload = payload
                    last_keepalive = now
                    yield payload
                elif now - last_keepalive >= INSTANCE_STREAM_KEEPALIVE_SECONDS:
                    last_keepalive = now
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[API] 实例状态流中断")
            yield serialize_error_event("instance_stream_failed", "实例状态流读取失败")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def get_instance(request: Request) -> JSONResponse:
    snapshot = request.app.state.instance_service.get(
        request.path_params["instance"]
    )
    return model_response(InstanceResponse.model_validate(snapshot))
