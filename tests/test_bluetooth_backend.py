import unittest
from unittest.mock import patch

from core.bluetooth_backend import BluetoothBackend, BluetoothDevice


class FakeBleController:
    def __init__(self, is_connected=False):
        self.is_connected = is_connected
        self.sent = []
        self.started = 0

    def send_cmd(self, packet):
        self.sent.append(packet)
        return True

    def start(self, *_args):
        self.started += 1

    def stop(self):
        pass


class BluetoothBackendTests(unittest.TestCase):
    def setUp(self):
        self.dbus_patch = patch("core.bluetooth_backend.dbus", None)
        self.dbus_patch.start()
        self.backend = BluetoothBackend()
        self.ble = FakeBleController()
        self.backend.ble_controller = self.ble
        self.backend._running = True
        self.backend.connected_device = BluetoothDevice(
            "/org/bluez/hci0/dev_00_11_22_33_44_55",
            "JBL Tune Buds 2",
            "00:11:22:33:44:55",
            True,
        )

    def tearDown(self):
        self.backend._running = False
        self.dbus_patch.stop()

    def test_disconnect_clears_queued_commands(self):
        self.backend.send_raw(bytes.fromhex("AA 25 01 01"))
        self.backend.send_raw(bytes.fromhex("F0 DC 01 00 01 00 01 00 01"))

        self.backend.disconnect()

        self.assertTrue(self.backend._send_queue.empty())
        self.assertTrue(self.backend._ble_only_queue.empty())

    def test_flush_routes_each_command_through_ble_once(self):
        protocol3 = bytes.fromhex("AA 25 01 01")
        protocol4 = bytes.fromhex("F0 DC 01 00 01 00 01 00 01")
        self.backend.send_raw(protocol3)
        self.backend.send_raw(protocol4)
        self.ble.is_connected = True

        self.backend._on_ble_status_changed({"ble_connected": True})

        self.assertEqual(self.ble.sent, [protocol3, protocol4])
        self.assertTrue(self.backend._send_queue.empty())
        self.assertTrue(self.backend._ble_only_queue.empty())

    def test_expired_command_is_not_replayed_after_connection(self):
        packet = bytes.fromhex("AA 25 01 01")
        self.backend._send_queue.put((0.0, packet))
        self.ble.is_connected = True

        with patch("core.bluetooth_backend.time.monotonic", return_value=100.0):
            self.backend._flush_send_queue_to_ble(self.backend._send_queue)

        self.assertEqual(self.ble.sent, [])
        self.assertTrue(self.backend._send_queue.empty())

    def test_connecting_same_active_device_does_not_restart_workers(self):
        self.backend.connect(self.backend.connected_device)

        self.assertEqual(self.ble.started, 0)
        self.assertTrue(self.backend._running)


if __name__ == "__main__":
    unittest.main()
