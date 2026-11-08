import unittest

from ui.battery_alerts import BatteryAlertTracker


class BatteryAlertTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tracker = BatteryAlertTracker()

    def test_alerts_at_or_below_low_battery_threshold_once(self):
        self.assertTrue(self.tracker.should_alert("left", 20))
        self.assertFalse(self.tracker.should_alert("left", 15))

    def test_rearms_after_battery_is_recharged(self):
        self.assertTrue(self.tracker.should_alert("case", 10))
        self.assertFalse(self.tracker.should_alert("case", 50))
        self.assertTrue(self.tracker.should_alert("case", 20))

    def test_does_not_alert_while_component_is_charging(self):
        self.assertFalse(self.tracker.should_alert("right", 5, charging=True))
        self.assertTrue(self.tracker.should_alert("right", 5))

    def test_tracks_each_component_independently(self):
        self.assertTrue(self.tracker.should_alert("left", 10))
        self.assertTrue(self.tracker.should_alert("right", 10))

    def test_ignores_invalid_levels(self):
        for level in (-1, 101, None, "20"):
            with self.subTest(level=level):
                self.assertFalse(self.tracker.should_alert("case", level))


if __name__ == "__main__":
    unittest.main()
