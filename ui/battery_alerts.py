class BatteryAlertTracker:
    LOW_BATTERY_THRESHOLD = 20

    def __init__(self):
        self._alerted_components = set()

    def should_alert(self, component, level, charging=False):
        if not isinstance(level, (int, float)) or not 0 <= level <= 100:
            return False

        if level > self.LOW_BATTERY_THRESHOLD:
            self._alerted_components.discard(component)
            return False

        if charging or component in self._alerted_components:
            return False

        self._alerted_components.add(component)
        return True
