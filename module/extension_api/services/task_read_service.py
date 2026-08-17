"""实例任务调度状态的无副作用投影服务。"""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from module.config.task_priority import get_scheduler_tasks, parse_task_priority
from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import DataReadError, InstanceNotFoundError
from module.extension_api.types import TaskListSnapshot, TaskSnapshot
from module.logger import logger


class TaskReadService:
    """从标准化配置计算请求时刻的任务分类。"""

    LANGUAGE = "zh-CN"

    def __init__(self, facade: CoreFacade | None = None) -> None:
        self.facade = facade or CoreFacade()

    def get(self, instance: str) -> TaskListSnapshot:
        try:
            self.facade.require_instance(instance)
            config = self.facade.read_instance_config(instance)
            args = self.facade.read_instance_args(instance)
            i18n = self.facade.read_instance_i18n(instance, self.LANGUAGE)
            manager = self.facade.get_instance_manager(instance)
            now = self._effective_now(config)
            priority = self._priority_order(config, args)
            rank = {name: index for index, name in enumerate(priority)}

            due: list[TaskSnapshot] = []
            waiting: list[TaskSnapshot] = []
            disabled: list[TaskSnapshot] = []
            discovery_order: dict[str, int] = {}
            for task_name, task_data in config.items():
                if not isinstance(task_data, dict):
                    continue
                scheduler = task_data.get("Scheduler")
                if not isinstance(scheduler, dict):
                    continue
                command = scheduler.get("Command")
                if not isinstance(command, str) or not command or command == "Unknown":
                    continue
                if command in discovery_order:
                    continue
                discovery_order[command] = len(discovery_order)
                enabled = bool(scheduler.get("Enable", False))
                next_run_raw = scheduler.get("NextRun")
                next_run = next_run_raw if isinstance(next_run_raw, datetime) else None
                item = TaskSnapshot(
                    name=command,
                    display_name=self._task_name(i18n, command),
                    enabled=enabled,
                    state="disabled" if not enabled else "pending",
                    next_run=next_run,
                )
                if not enabled:
                    disabled.append(item)
                elif next_run is None or next_run < now:
                    due.append(item)
                else:
                    waiting.append(replace(item, state="waiting"))

            def priority_key(item: TaskSnapshot) -> tuple[int, int]:
                return (
                    rank.get(item.name, len(rank) + discovery_order[item.name]),
                    discovery_order[item.name],
                )

            due.sort(key=priority_key)
            disabled.sort(key=priority_key)
            waiting.sort(
                key=lambda item: (
                    item.next_run or datetime.min,
                    *priority_key(item),
                )
            )

            running: list[TaskSnapshot] = []
            if manager.alive and due:
                running.append(replace(due.pop(0), state="running"))

            return TaskListSnapshot(
                instance=instance,
                running=tuple(running),
                pending=tuple(due),
                waiting=tuple(waiting),
                disabled=tuple(disabled),
            )
        except InstanceNotFoundError:
            raise
        except Exception as exc:
            logger.exception(f"[API] 读取任务快照失败: {instance}")
            raise DataReadError("tasks") from exc

    def _effective_now(self, config: dict[str, Any]) -> datetime:
        now = self.facade.get_current_time()
        duration = self._get_nested(
            config,
            ("Alas", "Optimization", "TaskHoardingDuration"),
            0,
        )
        try:
            minutes = max(int(duration), 0)
        except (TypeError, ValueError):
            minutes = 0
        return now - timedelta(minutes=minutes)

    def _priority_order(
        self, config: dict[str, Any], args: dict[str, Any]
    ) -> list[str]:
        configured = self._get_nested(
            config,
            ("General", "YukikazeTaskManager", "TaskPriorityAdjustment"),
        )
        default = self._get_nested(
            args,
            (
                "General",
                "YukikazeTaskManager",
                "TaskPriorityAdjustment",
                "value",
            ),
        )
        ordered = parse_task_priority(configured or default)
        for task in get_scheduler_tasks(args):
            if task not in ordered:
                ordered.append(task)
        return ordered

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
    def _task_name(i18n: dict[str, Any], command: str) -> str:
        value = (
            i18n.get("Task", {}).get(command, {}).get("name")
            if isinstance(i18n.get("Task"), dict)
            else None
        )
        if not isinstance(value, str) or not value or value.endswith(".name"):
            return command
        return value
