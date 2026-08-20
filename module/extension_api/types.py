"""API 扩展内部使用的稳定数据类型。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class InstanceSnapshot:
    """实例运行状态快照。"""

    name: str
    module: str
    running: bool
    state: str


@dataclass(frozen=True)
class ConfigSnapshot:
    """经过标准化和脱敏的实例配置。"""

    instance: str
    module: str
    values: dict[str, Any]
    redacted_paths: tuple[str, ...]
    revision: str


@dataclass(frozen=True)
class ConfigChange:
    """一个经过传输层解析的配置路径变更。"""

    path: str
    value: Any


@dataclass(frozen=True)
class ConfigOptionSnapshot:
    """配置字段的一个可选值。"""

    value: Any
    label: str


@dataclass(frozen=True)
class ConfigFieldSnapshot:
    """客户端渲染配置字段所需的稳定元数据。"""

    key: str
    name: str
    display_name: str
    help: str
    widget_type: str
    default: Any
    options: tuple[ConfigOptionSnapshot, ...]
    display: str | None
    read_only: bool
    sensitive: bool


@dataclass(frozen=True)
class ConfigGroupSnapshot:
    """配置字段分组。"""

    name: str
    display_name: str
    help: str
    fields: tuple[ConfigFieldSnapshot, ...]


@dataclass(frozen=True)
class ConfigTaskSnapshot:
    """配置结构中的任务节点。"""

    name: str
    display_name: str
    help: str
    groups: tuple[ConfigGroupSnapshot, ...]


@dataclass(frozen=True)
class ConfigMenuSnapshot:
    """配置结构中的菜单节点。"""

    name: str
    display_name: str
    page: str | None
    menu_type: str | None
    tasks: tuple[ConfigTaskSnapshot, ...]


@dataclass(frozen=True)
class ConfigSchemaSnapshot:
    """模块感知并完成本地化的配置结构。"""

    instance: str
    module: str
    language: str
    menus: tuple[ConfigMenuSnapshot, ...]


@dataclass(frozen=True)
class TaskSnapshot:
    """一个任务在请求时刻的调度状态。"""

    name: str
    display_name: str
    enabled: bool
    state: str
    next_run: datetime | None


@dataclass(frozen=True)
class TaskListSnapshot:
    """实例的任务分类快照。"""

    instance: str
    running: tuple[TaskSnapshot, ...]
    pending: tuple[TaskSnapshot, ...]
    waiting: tuple[TaskSnapshot, ...]
    disabled: tuple[TaskSnapshot, ...]


@dataclass(frozen=True)
class InstanceActionSnapshot:
    """实例生命周期操作及其操作后状态。"""

    action: str
    changed: bool
    instance: InstanceSnapshot


@dataclass(frozen=True)
class TaskActionSnapshot:
    """任务立即运行操作的稳定结果。"""

    instance: str
    task: str
    action: str
    scheduled_at: datetime
    scheduler_running: bool


@dataclass(frozen=True)
class LogLineSnapshot:
    """带客户端可转换时间戳的一行日志。"""

    content: str
    timestamp_ms: int | None


@dataclass(frozen=True)
class LogTailSnapshot:
    """有界的实例日志尾部。"""

    instance: str
    source: str
    lines: tuple[str, ...]
    count: int
    truncated: bool
    format: str = "plain"
    entries: tuple[LogLineSnapshot, ...] = ()
