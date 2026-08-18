"""REST API 请求与响应模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    """统一使用 camelCase 输出，便于独立 Web 客户端消费。"""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        from_attributes=True,
        populate_by_name=True,
    )


class HealthResponse(ApiModel):
    status: str = "ok"
    api_version: str


class SystemResponse(ApiModel):
    api_version: str
    core_commit: str
    python_version: str
    platform: str
    capabilities: list[str]


class InstanceResponse(ApiModel):
    name: str
    module: str
    running: bool
    state: str


class InstanceListResponse(ApiModel):
    items: list[InstanceResponse]


class LiveScreenshotStreamResponse(ApiModel):
    """实例实时截图的媒体连接描述。"""

    instance: str
    transport: str = "websocket"
    path: str = "/ws/live_screenshot"
    codec: str = "h264"
    modes: list[str] = Field(default_factory=lambda: ["auto", "scrcpy", "screenshot"])
    default_mode: str = "auto"
    default_fps: int = 60
    default_width: int = 640
    default_bitrate_scale: float = 1.0


class ConfigResponse(ApiModel):
    instance: str
    module: str
    values: dict[str, Any]
    redacted_paths: list[str]


class ConfigOptionResponse(ApiModel):
    value: Any
    label: str


class ConfigFieldResponse(ApiModel):
    key: str
    name: str
    display_name: str
    help: str
    widget_type: str
    default: Any
    options: list[ConfigOptionResponse]
    display: str | None
    read_only: bool
    sensitive: bool


class ConfigGroupResponse(ApiModel):
    name: str
    display_name: str
    help: str
    fields: list[ConfigFieldResponse]


class ConfigTaskResponse(ApiModel):
    name: str
    display_name: str
    help: str
    groups: list[ConfigGroupResponse]


class ConfigMenuResponse(ApiModel):
    name: str
    display_name: str
    page: str | None
    menu_type: str | None
    tasks: list[ConfigTaskResponse]


class ConfigSchemaResponse(ApiModel):
    instance: str
    module: str
    language: str
    menus: list[ConfigMenuResponse]


class TaskResponse(ApiModel):
    name: str
    display_name: str
    enabled: bool
    state: str
    next_run: datetime | None


class TaskListResponse(ApiModel):
    instance: str
    running: list[TaskResponse]
    pending: list[TaskResponse]
    waiting: list[TaskResponse]
    disabled: list[TaskResponse]


class LogLineResponse(ApiModel):
    content: str
    timestamp_ms: int | None


class LogTailResponse(ApiModel):
    instance: str
    source: str
    lines: list[str]
    count: int
    truncated: bool
    format: str = "plain"
    entries: list[LogLineResponse] = Field(default_factory=list)


class ErrorDetail(ApiModel):
    code: str
    message: str


class ErrorResponse(ApiModel):
    error: ErrorDetail
