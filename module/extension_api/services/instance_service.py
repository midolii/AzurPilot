"""AzurPilot 实例只读查询服务。"""

from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import InstanceNotFoundError
from module.extension_api.types import InstanceSnapshot


INSTANCE_STATE_NAMES = {
    1: "running",
    2: "inactive",
    3: "warning",
    4: "updating",
}


class InstanceService:
    """将 ProcessManager 状态转换为稳定的 API 快照。"""

    def __init__(self, facade: CoreFacade | None = None) -> None:
        self.facade = facade or CoreFacade()

    def list(self) -> list[InstanceSnapshot]:
        return [self._snapshot(name) for name in self.facade.list_instance_names()]

    def get(self, instance: str) -> InstanceSnapshot:
        if instance not in self.facade.list_instance_names():
            raise InstanceNotFoundError(instance)
        return self._snapshot(instance)

    def _snapshot(self, instance: str) -> InstanceSnapshot:
        manager = self.facade.get_instance_manager(instance)
        raw_state = manager.state
        return InstanceSnapshot(
            name=instance,
            module=self.facade.get_instance_module(instance),
            running=manager.alive,
            state=INSTANCE_STATE_NAMES.get(raw_state, "unknown"),
        )
