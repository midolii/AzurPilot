"""实例配置值与配置结构的只读投影服务。"""

from datetime import date, datetime, time
from typing import Any

from module.config.server import to_server
from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import (
    DataReadError,
    InstanceNotFoundError,
    InvalidLanguageError,
)
from module.extension_api.sensitive import SensitiveValuePolicy
from module.extension_api.types import (
    ConfigFieldSnapshot,
    ConfigGroupSnapshot,
    ConfigMenuSnapshot,
    ConfigOptionSnapshot,
    ConfigSchemaSnapshot,
    ConfigSnapshot,
    ConfigTaskSnapshot,
)
from module.logger import logger


def json_safe(value: Any) -> Any:
    """递归转换为稳定的 JSON 原生值。"""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, set):
        return [json_safe(item) for item in sorted(value, key=str)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class ConfigReadService:
    """从上游配置文档构建稳定且脱敏的 API 快照。"""

    DEFAULT_LANGUAGE = "zh-CN"

    def __init__(
        self,
        facade: CoreFacade | None = None,
        sensitive_policy: SensitiveValuePolicy | None = None,
    ) -> None:
        self.facade = facade or CoreFacade()
        self.sensitive_policy = sensitive_policy or SensitiveValuePolicy()
        self._schema_cache: dict[
            tuple[str, str, str], tuple[ConfigMenuSnapshot, ...]
        ] = {}

    def get_config(self, instance: str) -> ConfigSnapshot:
        try:
            self.facade.require_instance(instance)
            module = self.facade.get_instance_module(instance)
            config = self.facade.read_instance_config(instance)
            redacted = self.sensitive_policy.redact_config(config)
            return ConfigSnapshot(
                instance=instance,
                module=module,
                values=json_safe(redacted.values),
                redacted_paths=redacted.redacted_paths,
            )
        except InstanceNotFoundError:
            raise
        except Exception as exc:
            logger.exception(f"[API] 读取实例配置失败: {instance}")
            raise DataReadError("config") from exc

    def get_schema(
        self, instance: str, language: str | None = None
    ) -> ConfigSchemaSnapshot:
        language = language or self.DEFAULT_LANGUAGE
        try:
            self.facade.require_instance(instance)
            if language not in self.facade.get_supported_languages():
                raise InvalidLanguageError(language)

            module = self.facade.get_instance_module(instance)
            config = self.facade.read_instance_config(instance)
            package_name = self._get_nested(
                config, ("Alas", "Emulator", "PackageName"), "cn"
            )
            server = to_server(package_name if isinstance(package_name, str) else "cn")
            cache_key = (module, language, server)
            menus = self._schema_cache.get(cache_key)
            if menus is None:
                menus = self._build_menus(
                    self.facade.read_instance_menu(instance),
                    self.facade.read_instance_args(instance),
                    self.facade.read_instance_i18n(instance, language),
                    server,
                )
                self._schema_cache[cache_key] = menus

            return ConfigSchemaSnapshot(
                instance=instance,
                module=module,
                language=language,
                menus=menus,
            )
        except (InstanceNotFoundError, InvalidLanguageError):
            raise
        except Exception as exc:
            logger.exception(f"[API] 读取配置结构失败: {instance}")
            raise DataReadError("config_schema") from exc

    @staticmethod
    def _get_nested(
        data: dict[str, Any], path: tuple[str, ...], default: Any = None
    ) -> Any:
        current: Any = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    @staticmethod
    def _translated(value: Any, fallback: str) -> str:
        if not isinstance(value, str) or not value or value.endswith(
            (".name", ".help")
        ):
            return fallback
        return value

    def _build_menus(
        self,
        menu_data: dict[str, Any],
        args_data: dict[str, Any],
        i18n_data: dict[str, Any],
        server: str,
    ) -> tuple[ConfigMenuSnapshot, ...]:
        menus: list[ConfigMenuSnapshot] = []
        for menu_name, raw_menu in menu_data.items():
            if not isinstance(raw_menu, dict):
                continue
            tasks: list[ConfigTaskSnapshot] = []
            for task_name in raw_menu.get("tasks", []):
                task_args = args_data.get(task_name)
                if not isinstance(task_name, str) or not isinstance(task_args, dict):
                    continue
                task = self._build_task(
                    task_name, task_args, i18n_data, server
                )
                if task.groups:
                    tasks.append(task)
            if not tasks:
                continue

            menu_i18n = self._get_nested(
                i18n_data, ("Menu", str(menu_name), "name"), str(menu_name)
            )
            menus.append(
                ConfigMenuSnapshot(
                    name=str(menu_name),
                    display_name=self._translated(menu_i18n, str(menu_name)),
                    page=self._optional_string(raw_menu.get("page")),
                    menu_type=self._optional_string(raw_menu.get("menu")),
                    tasks=tuple(tasks),
                )
            )
        return tuple(menus)

    def _build_task(
        self,
        task_name: str,
        task_args: dict[str, Any],
        i18n_data: dict[str, Any],
        server: str,
    ) -> ConfigTaskSnapshot:
        groups: list[ConfigGroupSnapshot] = []
        for group_name, group_args in task_args.items():
            if not isinstance(group_args, dict):
                continue
            fields: list[ConfigFieldSnapshot] = []
            for field_name, definition in group_args.items():
                if not isinstance(definition, dict):
                    continue
                field = self._build_field(
                    task_name,
                    str(group_name),
                    str(field_name),
                    definition,
                    i18n_data,
                    server,
                )
                if field is not None:
                    fields.append(field)
            if not fields:
                continue

            group_i18n = self._get_nested(
                i18n_data, (str(group_name), "_info"), {}
            )
            if not isinstance(group_i18n, dict):
                group_i18n = {}
            groups.append(
                ConfigGroupSnapshot(
                    name=str(group_name),
                    display_name=self._translated(
                        group_i18n.get("name"), str(group_name)
                    ),
                    help=self._translated(group_i18n.get("help"), ""),
                    fields=tuple(fields),
                )
            )

        task_i18n = self._get_nested(i18n_data, ("Task", task_name), {})
        if not isinstance(task_i18n, dict):
            task_i18n = {}
        return ConfigTaskSnapshot(
            name=task_name,
            display_name=self._translated(task_i18n.get("name"), task_name),
            help=self._translated(task_i18n.get("help"), ""),
            groups=tuple(groups),
        )

    def _build_field(
        self,
        task_name: str,
        group_name: str,
        field_name: str,
        definition: dict[str, Any],
        i18n_data: dict[str, Any],
        server: str,
    ) -> ConfigFieldSnapshot | None:
        display = self._optional_string(definition.get("display"))
        widget_type = str(definition.get("type") or "input")
        if display == "hide" or widget_type == "storage":
            return None

        raw_options = definition.get("option", [])
        options = list(raw_options) if isinstance(raw_options, list) else []
        server_options = definition.get(f"option_{server}")
        if isinstance(server_options, list):
            if widget_type == "select" and server_options:
                options = list(server_options)
            else:
                options = [option for option in options if option in server_options]
        if (
            task_name == "GemsFarming"
            and group_name == "Campaign"
            and field_name == "Event"
            and widget_type == "select"
            and len(options) == 1
        ):
            return None

        field_i18n = self._get_nested(
            i18n_data, (group_name, field_name), {}
        )
        if not isinstance(field_i18n, dict):
            field_i18n = {}
        option_snapshots = tuple(
            ConfigOptionSnapshot(
                value=json_safe(option),
                label=self._translated(field_i18n.get(str(option)), str(option)),
            )
            for option in options
        )
        path = f"{task_name}.{group_name}.{field_name}"
        return ConfigFieldSnapshot(
            key=path,
            name=field_name,
            display_name=self._translated(field_i18n.get("name"), field_name),
            help=self._translated(field_i18n.get("help"), ""),
            widget_type=widget_type,
            default=json_safe(definition.get("value")),
            options=option_snapshots,
            display=display,
            read_only=(
                display in {"readonly", "disabled"}
                or widget_type in {"lock", "state", "stored", "storage"}
            ),
            sensitive=self.sensitive_policy.is_sensitive(path),
        )

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return str(value) if value is not None else None
