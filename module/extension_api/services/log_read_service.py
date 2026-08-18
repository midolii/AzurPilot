"""实例日志尾部的安全只读服务。"""

import io
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text

from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import (
    DataReadError,
    InstanceNotFoundError,
    InvalidQueryError,
)
from module.extension_api.sensitive import SensitiveValuePolicy
from module.extension_api.types import LogLineSnapshot, LogTailSnapshot
from module.logger import logger


class LogReadService:
    """读取内存日志快照，并在必要时回退轮转文件。"""

    DEFAULT_LIMIT = 200
    MAX_LIMIT = 400
    _timestamp_pattern = re.compile(
        r"(?:^|\s)(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})(?:\s|\s*[│|])"
    )

    def __init__(
        self,
        facade: CoreFacade | None = None,
        sensitive_policy: SensitiveValuePolicy | None = None,
    ) -> None:
        self.facade = facade or CoreFacade()
        self.sensitive_policy = sensitive_policy or SensitiveValuePolicy()

    def get(
        self,
        instance: str,
        limit: str | int | None = None,
        output_format: str | None = None,
    ) -> LogTailSnapshot:
        parsed_limit = self.parse_limit(limit)
        parsed_format = self.parse_output_format(output_format)
        try:
            self.facade.require_instance(instance)
            config = self.facade.read_instance_config(instance)
            secrets = self.sensitive_policy.redact_config(config).sensitive_values
            renderables = self.facade.get_instance_log_renderables(instance)
            if renderables:
                source = "memory"
                response_format = parsed_format
                lines = self._render_lines(renderables, ansi=parsed_format == "ansi")
                truncated = len(lines) > parsed_limit
                lines = lines[-parsed_limit:]
            else:
                log_file = self.facade.get_latest_instance_log_file(instance)
                if log_file is None:
                    source = "none"
                    response_format = "plain"
                    lines = []
                    truncated = False
                else:
                    source = "file"
                    # 文件处理器只保存纯文本，无法还原 Rich 的原始样式。
                    response_format = "plain"
                    lines, truncated = self._read_file_tail(log_file, parsed_limit)

            redacted_lines = tuple(
                self._redact_rendered_line(
                    line,
                    secrets,
                    preserve_ansi=response_format == "ansi",
                )
                for line in lines
            )
            entries = tuple(
                LogLineSnapshot(
                    content=line,
                    timestamp_ms=self._parse_timestamp_ms(line),
                )
                for line in redacted_lines
            )
            return LogTailSnapshot(
                instance=instance,
                source=source,
                lines=redacted_lines,
                count=len(redacted_lines),
                truncated=truncated,
                format=response_format,
                entries=entries,
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
    def parse_output_format(output_format: str | None) -> str:
        if output_format is None:
            return "plain"
        normalized = output_format.strip().lower()
        if normalized not in {"ansi", "plain"}:
            raise InvalidQueryError("format")
        return normalized

    @staticmethod
    def _render_lines(renderables: list[Any], ansi: bool = False) -> list[str]:
        output = io.StringIO()
        console = Console(
            file=output,
            color_system="truecolor" if ansi else None,
            force_terminal=ansi,
            no_color=not ansi,
            highlight=False,
            width=119,
        )
        for renderable in renderables:
            console.print(renderable)
        return output.getvalue().splitlines()

    def _redact_rendered_line(
        self,
        line: str,
        secrets: tuple[str, ...],
        preserve_ansi: bool,
    ) -> str:
        plain_line = Text.from_ansi(line).plain if preserve_ansi else line
        redacted_line = self.sensitive_policy.redact_text(plain_line, secrets)
        if preserve_ansi and redacted_line == plain_line:
            return line
        # ANSI 样式可能切断敏感值的字符序列；命中脱敏时降级成纯文本最安全。
        return redacted_line

    @classmethod
    def _parse_timestamp_ms(cls, line: str) -> int | None:
        plain_line = Text.from_ansi(line).plain
        match = cls._timestamp_pattern.search(plain_line)
        if not match:
            return None
        try:
            local_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S.%f").astimezone()
        except ValueError:
            return None
        return int(local_time.timestamp() * 1000)

    @staticmethod
    def _read_file_tail(path: Path, limit: int) -> tuple[list[str], bool]:
        lines: deque[str] = deque(maxlen=limit + 1)
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                lines.append(line.rstrip("\r\n"))
        truncated = len(lines) > limit
        selected = list(lines)
        return (selected[-limit:] if truncated else selected), truncated
