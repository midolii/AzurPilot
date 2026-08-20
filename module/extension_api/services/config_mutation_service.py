"""配置写入与任务立即运行服务。"""

import copy
import threading
from typing import Any

from module.config.deep import deep_get, deep_set
from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import (
    ConfigRevisionConflictError,
    ConfigValidationError,
    DataWriteError,
    InstanceNotFoundError,
    TaskDisabledError,
    TaskNotFoundError,
)
from module.extension_api.services.config_read_service import (
    ConfigReadService,
    config_revision,
)
from module.extension_api.types import (
    ConfigChange,
    ConfigFieldSnapshot,
    ConfigSnapshot,
    TaskActionSnapshot,
)
from module.logger import logger
from module.webui.utils import parse_pin_value, re_fullmatch


class ConfigMutationService:
    """在实例级锁内复用上游解析、回调和原子写入行为。"""

    def __init__(
        self,
        facade: CoreFacade | None = None,
        read_service: ConfigReadService | None = None,
    ) -> None:
        self.facade = facade or CoreFacade()
        self.read_service = read_service or ConfigReadService(self.facade)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def patch(
        self,
        instance: str,
        expected_revision: str,
        changes: tuple[ConfigChange, ...],
    ) -> ConfigSnapshot:
        """校验并批量保存客户端基于同一 revision 提交的配置变更。"""
        try:
            self.facade.require_instance(instance)
            with self._instance_lock(instance):
                config = self.facade.read_instance_config(instance)
                if config_revision(config) != expected_revision:
                    raise ConfigRevisionConflictError

                schema = self.read_service.get_schema(instance)
                writable_fields = {
                    field.key: field
                    for menu in schema.menus
                    for task in menu.tasks
                    for group in task.groups
                    for field in group.fields
                    if not field.read_only
                }
                args = self.facade.read_instance_args(instance)
                updater = self.facade.get_config_updater(instance)
                updated = copy.deepcopy(config)
                changed_paths: list[str] = []

                for change in changes:
                    field = writable_fields.get(change.path)
                    if field is None:
                        raise ConfigValidationError(change.path, "配置路径不可写")
                    definition = deep_get(args, change.path)
                    if not isinstance(definition, dict):
                        raise ConfigValidationError(change.path)

                    value = self._parse_value(change, field, definition)
                    deep_set(updated, change.path, value)
                    changed_paths.append(change.path)
                    for callback_path, callback_value in updater.save_callback(
                        change.path, value
                    ):
                        deep_set(updated, callback_path, callback_value)
                        changed_paths.append(callback_path)

                if config_revision(updated) != config_revision(config):
                    self.facade.write_instance_config(instance, updated)
                    logger.info(
                        f"[API] 已保存实例配置 {instance}: {sorted(set(changed_paths))}"
                    )
                return self.read_service.get_config(instance)
        except (
            ConfigRevisionConflictError,
            ConfigValidationError,
            InstanceNotFoundError,
        ):
            raise
        except Exception as exc:
            logger.exception(f"[API] 写入实例配置失败: {instance}")
            raise DataWriteError("config") from exc

    def run_task_now(self, instance: str, task: str) -> TaskActionSnapshot:
        """将启用任务的 NextRun 调整为当前时间，不创建并行 worker。"""
        try:
            self.facade.require_instance(instance)
            with self._instance_lock(instance):
                config = self.facade.read_instance_config(instance)
                task_key, scheduler = self._find_task_scheduler(config, task)
                if not bool(scheduler.get("Enable")):
                    raise TaskDisabledError(task)

                scheduled_at = self.facade.get_current_time().replace(microsecond=0)
                updated = copy.deepcopy(config)
                deep_set(updated, f"{task_key}.Scheduler.NextRun", scheduled_at)
                self.facade.write_instance_config(instance, updated)
                logger.info(f"[API] 实例 {instance} 的任务 {task} 已加入立即运行队列")
                return TaskActionSnapshot(
                    instance=instance,
                    task=task,
                    action="runNow",
                    scheduled_at=scheduled_at,
                    scheduler_running=self.facade.get_instance_manager(instance).alive,
                )
        except (InstanceNotFoundError, TaskDisabledError, TaskNotFoundError):
            raise
        except Exception as exc:
            logger.exception(f"[API] 调度任务失败: {instance}/{task}")
            raise DataWriteError("task") from exc

    def _instance_lock(self, instance: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(instance, threading.RLock())

    @staticmethod
    def _parse_value(
        change: ConfigChange,
        field: ConfigFieldSnapshot,
        definition: dict[str, Any],
    ) -> Any:
        widget_type = str(definition.get("type") or field.widget_type)
        value = parse_pin_value(
            change.value,
            definition.get("valuetype"),
            widget_type,
            definition.get("option"),
        )
        if len(str(value)) == 0:
            value = definition.get("value")

        validation = definition.get("validate")
        if validation and not re_fullmatch(validation, value):
            raise ConfigValidationError(change.path)

        option_values = tuple(option.value for option in field.options)
        if widget_type == "select" and option_values and value not in option_values:
            raise ConfigValidationError(change.path, "配置值不在可选范围内")
        if widget_type == "multiselect":
            if not isinstance(value, list):
                raise ConfigValidationError(change.path)
            if option_values and any(item not in option_values for item in value):
                raise ConfigValidationError(change.path, "配置值不在可选范围内")
        if widget_type == "checkbox" and not isinstance(value, bool):
            raise ConfigValidationError(change.path)
        return value

    @staticmethod
    def _find_task_scheduler(
        config: dict[str, Any], task: str
    ) -> tuple[str, dict[str, Any]]:
        for task_key, task_data in config.items():
            if not isinstance(task_data, dict):
                continue
            scheduler = task_data.get("Scheduler")
            if isinstance(scheduler, dict) and scheduler.get("Command") == task:
                return str(task_key), scheduler
        raise TaskNotFoundError(task)
