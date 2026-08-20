"""实例配置、任务和日志只读路由。"""

import asyncio
import json

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from module.extension_api.webapi.models import (
    ConfigResponse,
    ConfigSchemaResponse,
    LogTailResponse,
    TaskListResponse,
)
from module.extension_api.webapi.responses import model_response
from module.logger import logger

LOG_STREAM_POLL_INTERVAL_SECONDS = 1.0
LOG_STREAM_KEEPALIVE_SECONDS = 15.0


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


def _serialize_log_event(response: LogTailResponse, retry: int | None = None) -> str:
    payload = json.dumps(
        response.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    retry_field = f"retry: {retry}\n" if retry is not None else ""
    return f"{retry_field}event: logs\ndata: {payload}\n\n"


async def get_instance_logs_stream(request: Request) -> StreamingResponse:
    """持续推送有界日志尾部；首次事件同时承担初始快照。"""
    service = request.app.state.log_read_service
    instance = request.path_params["instance"]
    limit = request.query_params.get("limit")
    output_format = request.query_params.get("format")

    # 响应开始前完成首次读取，使无效参数和未知实例仍走统一 JSON 错误模型。
    initial_snapshot = await run_in_threadpool(
        service.get,
        instance,
        limit,
        output_format,
    )
    initial_response = LogTailResponse.model_validate(initial_snapshot)
    initial_payload = _serialize_log_event(initial_response, retry=2_000)

    async def event_generator():
        last_payload = _serialize_log_event(initial_response)
        last_keepalive = asyncio.get_running_loop().time()
        yield initial_payload

        try:
            while True:
                await asyncio.sleep(LOG_STREAM_POLL_INTERVAL_SECONDS)
                if await request.is_disconnected():
                    break

                snapshot = await run_in_threadpool(
                    service.get,
                    instance,
                    limit,
                    output_format,
                )
                response = LogTailResponse.model_validate(snapshot)
                payload = _serialize_log_event(response)
                now = asyncio.get_running_loop().time()
                if payload != last_payload:
                    last_payload = payload
                    last_keepalive = now
                    yield payload
                elif now - last_keepalive >= LOG_STREAM_KEEPALIVE_SECONDS:
                    last_keepalive = now
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            raise
        # 流式响应开始后无法再返回统一 JSON 错误，因此兜底转换为不泄露细节的 SSE 错误事件。
        except Exception:  # noqa: BLE001
            logger.exception(f"[API] 实例日志流中断: {instance}")
            error = json.dumps(
                {
                    "error": {
                        "code": "log_stream_failed",
                        "message": "实例日志流读取失败",
                    }
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield f"event: error\ndata: {error}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
