"""API 扩展内部使用的稳定数据类型。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class InstanceSnapshot:
    """实例运行状态快照。"""

    name: str
    module: str
    running: bool
    state: str
