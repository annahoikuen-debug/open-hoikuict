"""plan_docs.services.continuity の純関数ユニットテスト。DB接続不要。"""
from __future__ import annotations

import unittest
from datetime import date

from plan_docs.services.continuity import (
    common_field_keys_for_template,
    iso_week_monday,
    monthly_sheet_key,
    previous_business_day,
    previous_month,
)


class ContinuityHelpersTests(unittest.TestCase):
    def test_previous_month(self):
        self.assertEqual(previous_month("2026-03"), "2026-02")
        self.assertEqual(previous_month("2026-01"), "2025-12")
        self.assertEqual(previous_month("2026-04"), "2026-03")
        self.assertEqual(previous_month("2025-12"), "2025-11")
        with self.assertRaises(ValueError):
            previous_month("2026-13")
        with self.assertRaises(ValueError):
            previous_month("not-a-month")

    def test_iso_week_monday(self):
        # 2026-09-28 は月曜日
        self.assertEqual(iso_week_monday(date(2026, 9, 28)), date(2026, 9, 28))
        # 2026-10-02 は金曜日、その週の月曜日は 2026-09-28
        self.assertEqual(iso_week_monday(date(2026, 10, 2)), date(2026, 9, 28))
        # 年度替わり
        self.assertEqual(iso_week_monday(date(2027, 1, 4)), date(2027, 1, 4))

    def test_previous_business_day(self):
        # 火曜 → 月曜
        self.assertEqual(previous_business_day(date(2026, 10, 6)), date(2026, 10, 5))
        # 月曜 → 前週金曜
        self.assertEqual(previous_business_day(date(2026, 10, 5)), date(2026, 10, 2))
        # 木曜 → 水曜
        self.assertEqual(previous_business_day(date(2026, 10, 8)), date(2026, 10, 7))
        # 土曜 → 前週金曜
        self.assertEqual(previous_business_day(date(2026, 10, 10)), date(2026, 10, 9))
        # 日曜 → 前週金曜
        self.assertEqual(previous_business_day(date(2026, 10, 11)), date(2026, 10, 9))

    def test_common_field_keys_for_template(self):
        infant = common_field_keys_for_template(0)
        self.assertIn("common:goal", infant)
        self.assertIn("common:home", infant)
        self.assertIn("common:review", infant)
        self.assertIn("common:events", infant)
        self.assertNotIn("group:care:goal", infant)

        group = common_field_keys_for_template(3)
        self.assertIn("common:goal", group)
        self.assertIn("common:home", group)
        self.assertIn("common:review", group)
        self.assertNotIn("common:events", group)
        self.assertNotIn("child:1:life", group)

    def test_monthly_sheet_key(self):
        key = monthly_sheet_key("test-nursery", 1, "2026-10", 1)
        self.assertIn("test-nursery", key)
        self.assertIn("2026-10", key)
        key2 = monthly_sheet_key("test-nursery", 2, "2026-10", 1)
        self.assertNotEqual(key, key2)
