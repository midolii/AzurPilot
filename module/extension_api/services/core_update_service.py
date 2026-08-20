"""将原版 WebUI 更新器投影为稳定的 REST 服务。"""

import threading
from collections.abc import Callable
from typing import Any, ClassVar

from module.extension_api.errors import (
    CoreUpdateBusyError,
    CoreUpdateUnavailableError,
)
from module.extension_api.types import CoreCommitSnapshot, CoreUpdateSnapshot
from module.logger import logger


def _runtime_update_enabled() -> bool:
    """更新必须由 WebUI 主进程提供重启与依赖同步事件。"""
    from module.webui.setting import State

    return State.restart_event is not None and State.dependency_sync_event is not None


class CoreUpdateService:
    """复用 Updater 的事务式更新过程，REST 层只负责状态和触发。"""

    _STATUS: ClassVar[dict[Any, str]] = {
        0: "upToDate",
        1: "updateAvailable",
        "checking": "checking",
        "failed": "failed",
        "start": "starting",
        "wait": "waitingForInstances",
        "run update": "updating",
        "reload": "restarting",
        "finish": "finished",
        "cancel": "canceling",
    }

    def __init__(
        self,
        updater_instance: Any | None = None,
        enabled_provider: Callable[[], bool] | None = None,
    ) -> None:
        if updater_instance is None:
            from module.webui.updater import updater

            updater_instance = updater
        self.updater = updater_instance
        self.enabled_provider = enabled_provider or _runtime_update_enabled
        self._operation_lock = threading.Lock()
        self._apply_thread: threading.Thread | None = None

    def get(self) -> CoreUpdateSnapshot:
        branch = str(self.updater.Branch)
        local = self._commit(self.updater.get_commit(short_sha1=True))
        upstream = self._commit(
            self.updater.get_commit(f"origin/{branch}", short_sha1=True)
        )
        raw_history = self.updater.get_commit(f"origin/{branch}", n=20, short_sha1=True)
        history = self._history(raw_history)
        applying = self._apply_thread is not None and self._apply_thread.is_alive()
        raw_state = self.updater.state
        status = self._STATUS.get(raw_state, "unknown")
        if applying and raw_state in (1, "failed"):
            status = "starting"
        return CoreUpdateSnapshot(
            status=status,
            available=raw_state == 1,
            enabled=bool(self.enabled_provider()),
            source_repository=str(self.updater.Repository),
            source_branch=branch,
            local_commit=local,
            upstream_commit=upstream,
            history=history,
        )

    def check(self) -> CoreUpdateSnapshot:
        self.updater.check_update()
        return self.get()

    def apply(self) -> CoreUpdateSnapshot:
        with self._operation_lock:
            if self._apply_thread is not None and self._apply_thread.is_alive():
                raise CoreUpdateBusyError("核心更新已在执行")
            if not self.enabled_provider():
                raise CoreUpdateUnavailableError("当前部署不支持安全热更新")
            if self.updater.state not in (1, "failed"):
                raise CoreUpdateUnavailableError("当前没有可执行的核心更新")

            # HTTP 请求先返回，再由后台线程进入会停止实例并重启 WebUI 的事务。
            self._apply_thread = threading.Thread(
                target=self._run_apply,
                name="extension-api-core-update",
                daemon=True,
            )
            self._apply_thread.start()
        return self.get()

    def _run_apply(self) -> None:
        try:
            self.updater.run_update()
        except Exception as exc:  # noqa: BLE001 - 后台线程必须将未知异常转换为可重试状态
            logger.exception_context(
                title="[API] 核心更新执行异常",
                exc=exc,
                impact="更新已中止，请检查 WebUI 更新日志。",
                action="修复更新源或网络后重新检查更新。",
                level=50,
            )
            self.updater.state = "failed"

    @staticmethod
    def _commit(value: Any) -> CoreCommitSnapshot | None:
        if not isinstance(value, (tuple, list)) or len(value) < 4 or not value[0]:
            return None
        return CoreCommitSnapshot(
            sha1=str(value[0]),
            author=str(value[1] or ""),
            committed_at=str(value[2] or ""),
            message=str(value[3] or ""),
        )

    @classmethod
    def _history(cls, value: Any) -> tuple[CoreCommitSnapshot, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(
            commit for item in value if (commit := cls._commit(item)) is not None
        )
