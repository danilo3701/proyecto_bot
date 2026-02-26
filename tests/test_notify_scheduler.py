import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from notify_scheduler import normalize_notify_time, should_send_daily_notification

MADRID = ZoneInfo("Europe/Madrid")


class TestNotifyScheduler(unittest.TestCase):
    def test_default_on_for_blank_time(self):
        self.assertEqual(normalize_notify_time(""), "08:00")

    def test_three_test_users_mixed_times_due_and_not_due(self):
        now = datetime(2026, 1, 1, 9, 0, tzinfo=MADRID)
        u1 = {"notify_time": "08:00"}
        u2 = {"notify_time": "09:00"}
        u3 = {"notify_time": "10:00"}

        self.assertTrue(should_send_daily_notification(u1, now).due)
        self.assertTrue(should_send_daily_notification(u2, now).due)
        self.assertFalse(should_send_daily_notification(u3, now).due)

    def test_disable_and_enable_notifications(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=MADRID)
        off = {"notify_time": ""}
        on = {"notify_time": "08:00"}

        self.assertFalse(should_send_daily_notification(off, now).due)
        self.assertTrue(should_send_daily_notification(on, now).due)

    def test_only_once_per_day(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=MADRID)
        already = {"notify_time": "08:00", "last_notify_date": "2026-01-01"}
        self.assertFalse(should_send_daily_notification(already, now).due)


if __name__ == "__main__":
    unittest.main()
