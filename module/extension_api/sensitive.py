"""实例配置与日志共享的敏感值策略。"""

import json
import re
from dataclasses import dataclass
from typing import Any


REDACTED_TEXT = "[REDACTED]"


@dataclass(frozen=True)
class RedactedConfig:
    """脱敏后的配置副本及日志替换所需的秘密集合。"""

    values: dict[str, Any]
    redacted_paths: tuple[str, ...]
    sensitive_values: tuple[str, ...]


class SensitiveValuePolicy:
    """以明确路径为主、字段语义为辅识别敏感配置。"""

    _EXACT_PATHS = {
        "alas.error.llmapikey",
        "alas.error.onepushconfig",
        "alas.emulatorinfo.remotestartcommand",
        "alas.emulatorinfo.remotestopcommand",
        "emulatormanager.emulatormanager.remotestartcommand",
        "emulatormanager.emulatormanager.remotestopcommand",
    }
    _ALLOW_PATHS = {
        "alas.emulatorinfo.remotesshpublickey",
        "emulatormanager.emulatormanager.remotesshpublickey",
    }
    _SENSITIVE_PARTS = (
        "password",
        "passwd",
        "token",
        "secret",
        "credential",
        "apikey",
        "accesskey",
        "privatekey",
    )

    @staticmethod
    def _normalized_path(path: str) -> str:
        return path.casefold()

    @staticmethod
    def _normalized_name(path: str) -> str:
        leaf = path.rsplit(".", 1)[-1]
        return re.sub(r"[^a-z0-9]", "", leaf.casefold())

    def is_sensitive(self, path: str) -> bool:
        normalized_path = self._normalized_path(path)
        if normalized_path in self._ALLOW_PATHS:
            return False
        if normalized_path in self._EXACT_PATHS:
            return True
        normalized_name = self._normalized_name(path)
        return any(part in normalized_name for part in self._SENSITIVE_PARTS)

    def redact_config(self, config: dict[str, Any]) -> RedactedConfig:
        redacted_paths: list[str] = []
        sensitive_values: set[str] = set()

        def collect_sensitive(value: Any) -> None:
            if isinstance(value, str):
                if value:
                    sensitive_values.add(value)
            elif isinstance(value, bytes):
                if value:
                    sensitive_values.add(value.decode("utf-8", errors="replace"))
            elif isinstance(value, dict):
                for item in value.values():
                    collect_sensitive(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    collect_sensitive(item)

        def visit(value: Any, path: tuple[str, ...]) -> Any:
            path_text = ".".join(path)
            if path and self.is_sensitive(path_text):
                redacted_paths.append(path_text)
                collect_sensitive(value)
                return None
            if isinstance(value, dict):
                return {
                    str(key): visit(item, (*path, str(key)))
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [visit(item, path) for item in value]
            if isinstance(value, tuple):
                return tuple(visit(item, path) for item in value)
            if isinstance(value, set):
                return {visit(item, path) for item in value}
            return value

        values = visit(config, ())
        return RedactedConfig(
            values=values,
            redacted_paths=tuple(sorted(redacted_paths)),
            sensitive_values=tuple(sorted(sensitive_values, key=len, reverse=True)),
        )

    def redact_text(self, text: str, sensitive_values: tuple[str, ...]) -> str:
        """替换秘密的原值及常见字符串表示。"""
        variants: set[str] = set()
        for value in sensitive_values:
            if not value:
                continue
            variants.add(value)
            variants.add(repr(value))
            variants.add(json.dumps(value, ensure_ascii=False))

        redacted = text
        for value in sorted(variants, key=len, reverse=True):
            redacted = redacted.replace(value, REDACTED_TEXT)
        return redacted
