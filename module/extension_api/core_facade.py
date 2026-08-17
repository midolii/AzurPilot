"""隔离 API 扩展与 AzurPilot 上游内部实现。"""

import platform
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from module.config.utils import alas_instance
from module.submodule.utils import get_config_mod
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


class CoreFacade:
    """集中封装新 API 使用的上游入口。"""

    def list_instance_names(self) -> list[str]:
        return sorted(set(alas_instance()))

    def get_instance_manager(self, instance: str) -> ProcessManager:
        return ProcessManager.get_manager(instance)

    def get_instance_module(self, instance: str) -> str:
        return get_config_mod(instance)

    def get_core_commit(self) -> str:
        return _read_core_commit()

    @staticmethod
    def get_python_version() -> str:
        return platform.python_version()

    @staticmethod
    def get_platform() -> str:
        return sys.platform
