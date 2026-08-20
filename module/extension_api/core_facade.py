"""隔离 API 扩展与 AzurPilot 上游内部实现。"""

import importlib
import platform
import subprocess
import sys
from datetime import datetime
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from module.config.config_updater import ConfigUpdater
from module.config.time_source import now as current_time
from module.config.utils import (
    LANGUAGES,
    alas_instance,
    filepath_args,
    filepath_i18n,
    read_file,
)
from module.submodule.utils import get_config_mod, get_mod_dir
from module.webui.process_manager import ProcessManager

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _read_core_commit() -> str:
    """读取当前核心提交，失败时返回 unknown。"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"

    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else "unknown"


@cache
def _get_config_updater_class(module: str) -> type:
    """按实例模块定位不会构造运行时配置对象的更新器。"""
    if module == "alas":
        return ConfigUpdater

    module_dir = get_mod_dir(module)
    if not module_dir:
        raise ModuleNotFoundError(f"未知配置模块: {module}")
    config_module = importlib.import_module(
        f"submodule.{module_dir}.module.config.config_updater"
    )
    return config_module.ConfigUpdater


class CoreFacade:
    """集中封装新 API 使用的上游入口。"""

    def list_instance_names(self) -> list[str]:
        return sorted(set(alas_instance()))

    def get_instance_manager(self, instance: str) -> ProcessManager:
        return ProcessManager.get_manager(instance)

    def get_instance_module(self, instance: str) -> str:
        return get_config_mod(instance)

    def require_instance(self, instance: str) -> None:
        """确认实例属于当前部署，阻止未验证名称进入文件路径。"""
        from module.extension_api.errors import InstanceNotFoundError

        if instance not in self.list_instance_names():
            raise InstanceNotFoundError(instance)

    def get_config_updater(self, instance: str) -> Any:
        self.require_instance(instance)
        module = self.get_instance_module(instance)
        return _get_config_updater_class(module)()

    def read_instance_config(self, instance: str) -> dict[str, Any]:
        """读取标准化配置，不构造会保存数据的运行时配置实例。"""
        data = self.get_config_updater(instance).read_file(instance)
        if not isinstance(data, dict):
            raise TypeError("实例配置不是对象")
        return data

    def write_instance_config(self, instance: str, data: dict[str, Any]) -> None:
        """通过实例对应的上游 ConfigUpdater 原子写入配置文件。"""
        updater = self.get_config_updater(instance)
        updater.write_file(instance, data, self.get_instance_module(instance))

    def start_instance(self, instance: str) -> None:
        """复用原版 WebUI 的调度器启动语义。"""
        self.require_instance(instance)
        from module.webui.updater import updater

        self.get_instance_manager(instance).start(None, updater.event)

    def stop_instance(self, instance: str) -> bool:
        """复用原版 WebUI 的 worker 进程树停止逻辑。"""
        self.require_instance(instance)
        return bool(self.get_instance_manager(instance).stop())

    def _read_instance_document(
        self, instance: str, filename: str, language: str | None = None
    ) -> dict[str, Any]:
        self.require_instance(instance)
        module = self.get_instance_module(instance)
        path = (
            filepath_i18n(language, module)
            if language is not None
            else filepath_args(filename, module)
        )
        data = read_file(path)
        if not isinstance(data, dict):
            raise TypeError(f"配置文档不是对象: {filename}")
        return data

    def read_instance_args(self, instance: str) -> dict[str, Any]:
        return self._read_instance_document(instance, "args")

    def read_instance_menu(self, instance: str) -> dict[str, Any]:
        return self._read_instance_document(instance, "menu")

    def read_instance_i18n(
        self, instance: str, language: str
    ) -> dict[str, Any]:
        return self._read_instance_document(instance, "i18n", language)

    @staticmethod
    def get_supported_languages() -> tuple[str, ...]:
        return tuple(LANGUAGES)

    @staticmethod
    def get_current_time() -> datetime:
        return current_time()

    def get_instance_log_renderables(self, instance: str) -> list[Any]:
        self.require_instance(instance)
        manager = self.get_instance_manager(instance)
        return list(manager.renderables)

    def get_latest_instance_log_file(self, instance: str) -> Path | None:
        """返回日志目录内与已验证实例名匹配的最新普通文件。"""
        self.require_instance(instance)
        log_root = (PROJECT_ROOT / "log").resolve()
        if not log_root.is_dir():
            return None

        current_name = f"{instance}.txt"
        rotated_suffix = f"_{instance}.txt"
        candidates: list[Path] = []
        for candidate in log_root.iterdir():
            if not candidate.is_file():
                continue
            if candidate.name != current_name and not candidate.name.endswith(
                rotated_suffix
            ):
                continue
            resolved = candidate.resolve()
            if resolved.parent != log_root:
                continue
            candidates.append(resolved)

        if not candidates:
            return None
        return max(
            candidates,
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )

    def get_core_commit(self) -> str:
        return _read_core_commit()

    @staticmethod
    def get_python_version() -> str:
        return platform.python_version()

    @staticmethod
    def get_platform() -> str:
        return sys.platform
