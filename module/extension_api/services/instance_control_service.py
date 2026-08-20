"""实例 worker 生命周期操作服务。"""

from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import (
    DataWriteError,
    InstanceNotFoundError,
    InstanceOperationError,
)
from module.extension_api.services.instance_service import InstanceService
from module.extension_api.types import InstanceActionSnapshot
from module.logger import logger


class InstanceControlService:
    """以幂等 REST 操作包装原版 ProcessManager。"""

    def __init__(
        self,
        facade: CoreFacade | None = None,
        instance_service: InstanceService | None = None,
    ) -> None:
        self.facade = facade or CoreFacade()
        self.instance_service = instance_service or InstanceService(self.facade)

    def start(self, instance: str) -> InstanceActionSnapshot:
        try:
            self.facade.require_instance(instance)
            manager = self.facade.get_instance_manager(instance)
            changed = not manager.alive
            if changed:
                self.facade.start_instance(instance)
                if not manager.alive:
                    raise InstanceOperationError("start")
            return InstanceActionSnapshot(
                action="start",
                changed=changed,
                instance=self.instance_service.get(instance),
            )
        except (InstanceNotFoundError, InstanceOperationError):
            raise
        except Exception as exc:
            logger.exception(f"[API] 启动实例失败: {instance}")
            raise DataWriteError("instance") from exc

    def stop(self, instance: str) -> InstanceActionSnapshot:
        try:
            self.facade.require_instance(instance)
            manager = self.facade.get_instance_manager(instance)
            changed = bool(manager.alive)
            if changed and not self.facade.stop_instance(instance):
                raise InstanceOperationError("stop")
            return InstanceActionSnapshot(
                action="stop",
                changed=changed,
                instance=self.instance_service.get(instance),
            )
        except (InstanceNotFoundError, InstanceOperationError):
            raise
        except Exception as exc:
            logger.exception(f"[API] 停止实例失败: {instance}")
            raise DataWriteError("instance") from exc
