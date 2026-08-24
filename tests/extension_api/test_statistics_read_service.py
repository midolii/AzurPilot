import unittest
from types import SimpleNamespace

from module.extension_api.errors import InvalidQueryError
from module.extension_api.services.statistics_read_service import StatisticsReadService


class StatisticsReadServiceTest(unittest.TestCase):
    def setUp(self):
        self.facade = SimpleNamespace(require_instance=lambda _instance: None)

    def test_resource_rows_are_bounded_and_invalid_timestamps_are_ignored(self):
        service = StatisticsReadService(
            facade=self.facade,
            resource_reader=lambda _instance, _limit: [
                {"ts": "2026-08-21T12:00:00", "oil": "1200", "coin": 3400},
                {"ts": "invalid", "oil": 9999},
            ],
            commission_months_reader=lambda _instance: [],
            commission_reader=lambda _instance, _year, _month: [],
        )

        snapshot = service.get_resources("alas", 200)

        self.assertEqual(200, snapshot.limit)
        self.assertEqual(1, snapshot.count)
        self.assertEqual(1200, snapshot.items[0].oil)
        self.assertEqual(3400, snapshot.items[0].coin)

    def test_commissions_are_sorted_and_paginated_across_retained_months(self):
        entries = {
            (2026, 8): [
                {
                    "ts": "2026-08-20T12:00:00",
                    "items": {"Cubes": 2},
                    "commission_count": 4,
                },
                {
                    "ts": "2026-08-22T12:00:00",
                    "items": {"Coins": 1000},
                    "commission_count": 1,
                },
            ],
            (2026, 7): [
                {
                    "ts": "2026-07-30T12:00:00",
                    "items": {"Gems": 10},
                    "commission_count": 2,
                }
            ],
        }
        service = StatisticsReadService(
            facade=self.facade,
            resource_reader=lambda _instance, _limit: [],
            commission_months_reader=lambda _instance: ["2026-07", "2026-08"],
            commission_reader=lambda _instance, year, month: entries[(year, month)],
        )

        first_page = service.get_commissions("alas", page=1, page_size=2)
        second_page = service.get_commissions("alas", page=2, page_size=2)

        self.assertEqual(3, first_page.total)
        self.assertEqual(2, first_page.total_pages)
        self.assertEqual(["coin", "cube"], [item.rewards[0].key for item in first_page.items])
        self.assertEqual("gem", second_page.items[0].rewards[0].key)
        self.assertEqual(2, first_page.retention.retained_months)
        self.assertFalse(first_page.retention.automatic_month_cleanup)

    def test_invalid_pagination_is_rejected(self):
        service = StatisticsReadService(facade=self.facade)

        for parameter, page, page_size in (
            ("page", 0, 20),
            ("pageSize", 1, 0),
            ("pageSize", 1, 101),
        ):
            with self.subTest(parameter=parameter):
                with self.assertRaises(InvalidQueryError) as context:
                    service.get_commissions("alas", page=page, page_size=page_size)
                self.assertEqual(parameter, context.exception.parameter)


if __name__ == "__main__":
    unittest.main()
