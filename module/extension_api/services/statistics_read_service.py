"""实例资源趋势和委托历史的无副作用投影服务。"""

from collections.abc import Callable
from datetime import datetime, timedelta
from math import ceil
from typing import Any, ClassVar

from module.extension_api.core_facade import CoreFacade
from module.extension_api.errors import (
    DataReadError,
    InstanceNotFoundError,
    InvalidQueryError,
)
from module.extension_api.types import (
    CommissionPageSnapshot,
    CommissionPeriodSummarySnapshot,
    CommissionRecordSnapshot,
    CommissionRetentionSnapshot,
    CommissionRewardSnapshot,
    CommissionSummaryItemSnapshot,
    CommissionSummarySnapshot,
    ResourcePointSnapshot,
    ResourceTimelineSnapshot,
)
from module.logger import logger
from module.statistics.cl1_database import db as cl1_db
from module.statistics.resource_stats import get_resource_timeline


class StatisticsReadService:
    """将现有统计数据库投影成有界、稳定的 API 数据结构。"""

    DEFAULT_RESOURCE_LIMIT = 500
    MAX_RESOURCE_LIMIT = 1000
    RESOURCE_SCAN_LIMIT = 100_000
    DEFAULT_RESOURCE_PERIOD = "month"
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
    MAX_COMMISSION_ENTRIES_PER_MONTH = 5000
    _reward_keys: ClassVar[dict[str, str]] = {
        "Gem": "gem",
        "Gems": "gem",
        "Cube": "cube",
        "Cubes": "cube",
        "Chip": "chip",
        "CognitiveChips": "chip",
        "Oil": "oil",
        "Coin": "coin",
        "Coins": "coin",
    }
    _resource_keys = (
        "oil",
        "coin",
        "gem",
        "pt",
        "cube",
        "core",
        "medal",
        "merit",
        "guild_coin",
        "action_point",
        "yellow_coin",
        "purple_coin",
    )
    _resource_periods = ("day", "week", "month")
    _commission_summary_keys = ("gem", "cube", "chip", "oil", "coin")

    def __init__(
        self,
        facade: CoreFacade | None = None,
        resource_reader: Callable[[str, int], list[dict[str, Any]]] | None = None,
        commission_months_reader: Callable[[str], list[str]] | None = None,
        commission_reader: Callable[[str, int, int], list[dict[str, Any]]] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.facade = facade or CoreFacade()
        self.resource_reader = resource_reader or get_resource_timeline
        self.commission_months_reader = (
            commission_months_reader or cl1_db.get_commission_income_months
        )
        self.commission_reader = commission_reader or cl1_db.get_commission_income
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())

    def get_resources(
        self,
        instance: str,
        limit: str | int | None = None,
        period: str | None = None,
    ) -> ResourceTimelineSnapshot:
        parsed_limit = self._parse_positive_integer(
            "limit",
            limit,
            default=self.DEFAULT_RESOURCE_LIMIT,
            maximum=self.MAX_RESOURCE_LIMIT,
        )
        parsed_period = self._parse_resource_period(period)
        try:
            self.facade.require_instance(instance)
            rows = self.resource_reader(instance, self.RESOURCE_SCAN_LIMIT)
            period_start_ms = self._period_starts(self.now_provider())[parsed_period]
            all_points = tuple(
                point
                for row in rows
                if (point := self._resource_point(row)) is not None
                and point.timestamp_ms >= period_start_ms
            )
            points = self._sample_points(all_points, parsed_limit)
            return ResourceTimelineSnapshot(
                instance=instance,
                period=parsed_period,
                items=points,
                count=len(points),
                total_count=len(all_points),
                limit=parsed_limit,
                sampled=len(points) < len(all_points),
                available_from_ms=all_points[0].timestamp_ms if all_points else None,
                available_to_ms=all_points[-1].timestamp_ms if all_points else None,
            )
        except (InstanceNotFoundError, InvalidQueryError):
            raise
        except Exception as exc:
            logger.exception(f"[API] 读取资源趋势失败: {instance}")
            raise DataReadError("resource_statistics") from exc

    def get_commission_summary(self, instance: str) -> CommissionSummarySnapshot:
        """按原 WebUI 口径汇总今日、本周和本月的委托奖励。"""
        try:
            self.facade.require_instance(instance)
            records, _months = self._commission_records(instance)
            starts = self._period_starts(self.now_provider())
            periods = tuple(
                self._commission_period_summary(period, starts[period], records)
                for period in self._resource_periods
            )
            return CommissionSummarySnapshot(instance=instance, periods=periods)
        except (InstanceNotFoundError, InvalidQueryError):
            raise
        except Exception as exc:
            logger.exception(f"[API] 读取委托收益摘要失败: {instance}")
            raise DataReadError("commission_summary") from exc

    def get_commissions(
        self,
        instance: str,
        page: str | int | None = None,
        page_size: str | int | None = None,
    ) -> CommissionPageSnapshot:
        parsed_page = self._parse_positive_integer("page", page, default=1)
        parsed_page_size = self._parse_positive_integer(
            "pageSize",
            page_size,
            default=self.DEFAULT_PAGE_SIZE,
            maximum=self.MAX_PAGE_SIZE,
        )
        try:
            self.facade.require_instance(instance)
            records, months = self._commission_records(instance)
            total = len(records)
            total_pages = ceil(total / parsed_page_size) if total else 0
            start = (parsed_page - 1) * parsed_page_size
            selected = tuple(records[start : start + parsed_page_size])
            return CommissionPageSnapshot(
                instance=instance,
                items=selected,
                page=parsed_page,
                page_size=parsed_page_size,
                total=total,
                total_pages=total_pages,
                retention=CommissionRetentionSnapshot(
                    available_from_ms=records[-1].timestamp_ms if records else None,
                    available_to_ms=records[0].timestamp_ms if records else None,
                    retained_months=len(months),
                    max_entries_per_month=self.MAX_COMMISSION_ENTRIES_PER_MONTH,
                    automatic_month_cleanup=False,
                ),
            )
        except (InstanceNotFoundError, InvalidQueryError):
            raise
        except Exception as exc:
            logger.exception(f"[API] 读取委托历史失败: {instance}")
            raise DataReadError("commission_statistics") from exc

    def _commission_records(
        self, instance: str
    ) -> tuple[list[CommissionRecordSnapshot], list[str]]:
        months = sorted(set(self.commission_months_reader(instance)), reverse=True)
        records: list[CommissionRecordSnapshot] = []
        for month_key in months:
            parsed_month = self._parse_month(month_key)
            if parsed_month is None:
                continue
            year, month = parsed_month
            records.extend(
                record
                for entry in self.commission_reader(instance, year, month)
                if (record := self._commission_record(entry)) is not None
            )
        records.sort(key=lambda item: item.timestamp_ms, reverse=True)
        return records, months

    def _commission_period_summary(
        self,
        period: str,
        starts_at_ms: int,
        records: list[CommissionRecordSnapshot],
    ) -> CommissionPeriodSummarySnapshot:
        totals = {key: 0 for key in self._commission_summary_keys}
        counts = {key: 0 for key in self._commission_summary_keys}
        total_commissions = 0
        for record in records:
            if record.timestamp_ms < starts_at_ms:
                break
            total_commissions += record.commission_count
            for reward in record.rewards:
                if reward.key not in totals:
                    continue
                totals[reward.key] += reward.amount
                # 与原 WebUI 一致：次数表示包含该奖励的结算记录数。
                counts[reward.key] += 1

        items = tuple(
            CommissionSummaryItemSnapshot(
                key=key,
                total=totals[key],
                count=counts[key],
                average=round(totals[key] / counts[key], 1) if counts[key] else 0,
            )
            for key in self._commission_summary_keys
        )
        return CommissionPeriodSummarySnapshot(
            period=period,
            starts_at_ms=starts_at_ms,
            total_commissions=total_commissions,
            items=items,
        )

    @classmethod
    def _resource_point(cls, row: dict[str, Any]) -> ResourcePointSnapshot | None:
        timestamp_ms = cls._timestamp_ms(row.get("ts"))
        if timestamp_ms is None:
            return None
        values = {key: cls._optional_integer(row.get(key)) for key in cls._resource_keys}
        action_point_current = values["action_point"]
        action_point_total = cls._optional_integer(row.get("action_point_total"))
        if action_point_total is not None:
            values["action_point"] = action_point_total
        values["action_point_box"] = (
            max(action_point_total - action_point_current, 0)
            if action_point_total is not None and action_point_current is not None
            else None
        )
        return ResourcePointSnapshot(timestamp_ms=timestamp_ms, **values)

    @classmethod
    def _commission_record(
        cls, entry: dict[str, Any]
    ) -> CommissionRecordSnapshot | None:
        timestamp_ms = cls._timestamp_ms(entry.get("ts"))
        if timestamp_ms is None:
            return None
        raw_items = entry.get("items")
        if not isinstance(raw_items, dict):
            raw_items = {}
        rewards = tuple(
            CommissionRewardSnapshot(
                key=cls._reward_keys.get(str(key), str(key)),
                amount=amount,
            )
            for key, value in raw_items.items()
            if (amount := cls._optional_integer(value)) is not None
        )
        return CommissionRecordSnapshot(
            timestamp_ms=timestamp_ms,
            commission_count=max(cls._optional_integer(entry.get("commission_count")) or 1, 1),
            rewards=rewards,
        )

    @staticmethod
    def _parse_positive_integer(
        parameter: str,
        value: str | int | None,
        *,
        default: int,
        maximum: int | None = None,
    ) -> int:
        if value is None:
            return default
        if isinstance(value, bool):
            raise InvalidQueryError(parameter)
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise InvalidQueryError(parameter) from exc
        if parsed < 1 or (maximum is not None and parsed > maximum):
            raise InvalidQueryError(parameter)
        return parsed

    @classmethod
    def _parse_resource_period(cls, value: str | None) -> str:
        if value is None:
            return cls.DEFAULT_RESOURCE_PERIOD
        if value not in cls._resource_periods:
            raise InvalidQueryError("period")
        return value

    @staticmethod
    def _period_starts(now: datetime) -> dict[str, int]:
        local_now = now.astimezone()
        day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        week = day - timedelta(days=day.weekday())
        month = day.replace(day=1)
        return {
            "day": int(day.timestamp() * 1000),
            "week": int(week.timestamp() * 1000),
            "month": int(month.timestamp() * 1000),
        }

    @staticmethod
    def _sample_points(
        points: tuple[ResourcePointSnapshot, ...], limit: int
    ) -> tuple[ResourcePointSnapshot, ...]:
        """均匀抽取有界点集，并始终保留时间范围两端。"""
        if len(points) <= limit:
            return points
        if limit == 1:
            return (points[-1],)
        last_index = len(points) - 1
        indexes = {
            round(position * last_index / (limit - 1)) for position in range(limit)
        }
        return tuple(points[index] for index in sorted(indexes))

    @staticmethod
    def _parse_month(value: str) -> tuple[int, int] | None:
        try:
            year_text, month_text = value.split("-", maxsplit=1)
            year = int(year_text)
            month = int(month_text)
        except (AttributeError, TypeError, ValueError):
            return None
        if len(year_text) != 4 or len(month_text) != 2 or not 1 <= month <= 12:
            return None
        return year, month

    @staticmethod
    def _timestamp_ms(value: Any) -> int | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value).astimezone()
        except ValueError:
            return None
        return int(parsed.timestamp() * 1000)

    @staticmethod
    def _optional_integer(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
