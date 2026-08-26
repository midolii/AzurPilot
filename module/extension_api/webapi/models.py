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


class LiveControlCoordinateSpaceResponse(ApiModel):
    """浏览器控制事件使用的稳定坐标空间。"""

    width: int = 1280
    height: int = 720


class LiveControlStreamResponse(ApiModel):
    """实例实时控制连接描述。"""

    transport: str = "websocket"
    path: str = "/ws/live_control"
    protocol_version: int = 2
    coordinate_space: LiveControlCoordinateSpaceResponse = Field(
        default_factory=LiveControlCoordinateSpaceResponse
    )
    actions: list[str] = Field(
        default_factory=lambda: [
            "tap",
            "drag",
            "touch",
            "key",
            "text",
            "back",
            "home",
            "app_switch",
        ]
    )


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
    control: LiveControlStreamResponse = Field(default_factory=LiveControlStreamResponse)


class ConfigResponse(ApiModel):
    instance: str
    module: str
    values: dict[str, Any]
    redacted_paths: list[str]
    revision: str


class ConfigChangeRequest(ApiModel):
    path: str = Field(min_length=1, max_length=240)
    value: Any


class ConfigPatchRequest(ApiModel):
    expected_revision: str = Field(min_length=64, max_length=64)
    changes: list[ConfigChangeRequest] = Field(min_length=1, max_length=100)


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


class InstanceActionResponse(ApiModel):
    action: str
    changed: bool
    instance: InstanceResponse


class TaskActionResponse(ApiModel):
    instance: str
    task: str
    action: str
    scheduled_at: datetime
    scheduler_running: bool


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


class ResourcePointResponse(ApiModel):
    timestamp_ms: int
    oil: int | None
    coin: int | None
    gem: int | None
    pt: int | None
    cube: int | None
    core: int | None
    medal: int | None
    merit: int | None
    guild_coin: int | None
    action_point: int | None
    action_point_box: int | None
    yellow_coin: int | None
    purple_coin: int | None


class ResourceTimelineResponse(ApiModel):
    instance: str
    period: str
    items: list[ResourcePointResponse]
    count: int
    total_count: int
    limit: int
    sampled: bool
    available_from_ms: int | None
    available_to_ms: int | None


class CommissionRewardResponse(ApiModel):
    key: str
    amount: int


class CommissionRecordResponse(ApiModel):
    timestamp_ms: int
    commission_count: int
    rewards: list[CommissionRewardResponse]


class CommissionRetentionResponse(ApiModel):
    available_from_ms: int | None
    available_to_ms: int | None
    retained_months: int
    max_entries_per_month: int
    automatic_month_cleanup: bool


class CommissionPageResponse(ApiModel):
    instance: str
    items: list[CommissionRecordResponse]
    page: int
    page_size: int
    total: int
    total_pages: int
    retention: CommissionRetentionResponse


class CommissionSummaryItemResponse(ApiModel):
    key: str
    total: int
    count: int
    average: float


class CommissionPeriodSummaryResponse(ApiModel):
    period: str
    starts_at_ms: int
    total_commissions: int
    items: list[CommissionSummaryItemResponse]


class CommissionSummaryResponse(ApiModel):
    instance: str
    periods: list[CommissionPeriodSummaryResponse]


class CoreCommitResponse(ApiModel):
    sha1: str
    author: str
    committed_at: str
    message: str


class CoreUpdateResponse(ApiModel):
    status: str
    available: bool
    enabled: bool
    source_repository: str
    source_branch: str
    local_commit: CoreCommitResponse | None
    upstream_commit: CoreCommitResponse | None
    history: list[CoreCommitResponse]


class ErrorDetail(ApiModel):
    code: str
    message: str


class ErrorResponse(ApiModel):
    error: ErrorDetail
