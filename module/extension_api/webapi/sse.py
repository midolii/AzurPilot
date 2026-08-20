"""Server-Sent Events 的稳定序列化与响应头。"""

import json
from typing import Any

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def serialize_model_event(event: str, response: Any, retry: int | None = None) -> str:
    payload = json.dumps(
        response.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    retry_field = f"retry: {retry}\n" if retry is not None else ""
    return f"{retry_field}event: {event}\ndata: {payload}\n\n"


def serialize_error_event(code: str, message: str) -> str:
    payload = json.dumps(
        {"error": {"code": code, "message": message}},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: error\ndata: {payload}\n\n"
