"""实例日志尾部的安全只读服务。"""

import io
from collections import deque
from pathlib import Path
from typing import Any

from rich.console import Console

from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import (
    DataReadError,
    InstanceNotFoundError,
    InvalidQueryError,
)
from module.extension_api.sensitive import SensitiveValuePolicy
from module.extension_api.types import LogTailSnapshot
from module.logger import logger


class LogReadService:
    """读取内存日志快照，并在必要时回退轮转文件。"""

    DEFAULT_LIMIT = 200
    MAX_LIMIT = 400

    def __init__(
        self,
        facade: CoreFacade | None = None,
        sensitive_policy: SensitiveValuePolicy | None = None,
    ) -> None:
        self.facade = facade or CoreFacade()
        self.sensitive_policy = sensitive_policy or SensitiveValuePolicy()

    def get(self, instance: str, limit: str | int | None = None) -> LogTailSnapshot:
        parsed_limit = self.parse_limit(limit)
        try:
            self.facade.require_instance(instance)
            config = self.facade.read_instance_config(instance)
            secrets = self.sensitive_policy.redact_config(config).sensitive_values
            renderables = self.facade.get_instance_log_renderables(instance)
            if renderables:
                source = "memory"
                lines = self._render_lines(renderables)
                truncated = len(lines) > parsed_limit
                lines = lines[-parsed_limit:]
            else:
                log_file = self.facade.get_latest_instance_log_file(instance)
                if log_file is None:
                    source = "none"
                    lines = []
                    truncated = False
                else:
                    source = "file"
                    lines, truncated = self._read_file_tail(log_file, parsed_limit)

            redacted_lines = tuple(
                self.sensitive_policy.redact_text(line, secrets) for line in lines
            )
            return LogTailSnapshot(
                instance=instance,
                source=source,
                lines=redacted_lines,
                count=len(redacted_lines),
                truncated=truncated,
            )
        except InstanceNotFoundError:
            raise
        except Exception as exc:
            logger.exception(f"[API] 读取日志尾部失败: {instance}")
            raise DataReadError("logs") from exc

    @classmethod
    def parse_limit(cls, limit: str | int | None) -> int:
        if limit is None:
            return cls.DEFAULT_LIMIT
        if isinstance(limit, bool):
            raise InvalidQueryError("limit")
        try:
            parsed = int(limit)
        except (TypeError, ValueError) as exc:
            raise InvalidQueryError("limit") from exc
        if not 1 <= parsed <= cls.MAX_LIMIT:
            raise InvalidQueryError("limit")
        return parsed

    @staticmethod
    def _render_lines(renderables: list[Any]) -> list[str]:
        output = io.StringIO()
        console = Console(
            file=output,
            no_color=True,
            highlight=False,
            width=119,
        )
        for renderable in renderables:
            console.print(renderable)
        return output.getvalue().splitlines()

    @staticmethod
    def _read_file_tail(path: Path, limit: int) -> tuple[list[str], bool]:
        lines: deque[str] = deque(maxlen=limit + 1)
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                lines.append(line.rstrip("\r\n"))
        truncated = len(lines) > limit
        selected = list(lines)
        return (selected[-limit:] if truncated else selected), truncated
