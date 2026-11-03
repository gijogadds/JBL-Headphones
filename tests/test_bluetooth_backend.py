import contextlib
import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.bluetooth_backend import BluetoothBackend, BluetoothDevice
from core.ble_controller import (
    BLEController,
    HARMAN_ADVERTISING_SERVICE_UUID,
    HARMAN_SERVICE_UUID,
)


class FakeBleController:
    def __init__(self, is_connected=False):
        self.is_connected = is_connected
        self.has_control_candidate = False
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

    def test_shutdown_socket_close_does_not_log_as_communication_error(self):
        recv_started = threading.Event()
        allow_closed_recv = threading.Event()
        stderr = io.StringIO()

        class ClosingSocket:
            def recv(self, _size):
                recv_started.set()
                allow_closed_recv.wait(timeout=2)
                raise OSError(9, "Bad file descriptor")

            def close(self):
                pass

        self.backend._rfcomm_socket = ClosingSocket()
        worker = threading.Thread(target=self.backend._run_loop)
        with contextlib.redirect_stderr(stderr):
            worker.start()
            self.assertTrue(recv_started.wait(timeout=2))
            self.backend._running = False
            allow_closed_recv.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertNotIn("Erro no loop de comunicação", stderr.getvalue())

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

    def test_control_uses_ble_when_connected(self):
        packet = bytes.fromhex("AA 91 01 13")
        self.ble.is_connected = True

        self.assertTrue(self.backend.send_control(packet))

        self.assertEqual(self.ble.sent, [packet])
        self.assertTrue(self.backend._send_queue.empty())

    def test_control_keeps_rfcomm_compatibility_without_ble_target(self):
        packet = bytes.fromhex("AA 91 01 13")

        self.assertTrue(self.backend.send_control(packet))

        self.assertEqual(self.backend._send_queue.qsize(), 1)

    def test_control_does_not_fall_back_to_rfcomm_for_harman_ble_target(self):
        packet = bytes.fromhex("AA 91 01 13")
        self.ble.has_control_candidate = True
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            sent = self.backend.send_control(packet)

        self.assertFalse(sent)
        self.assertTrue(self.backend._send_queue.empty())
        self.assertIn("GATT ainda não está conectado", stderr.getvalue())

    def test_protocol4_control_is_not_reported_as_sent_without_gatt(self):
        packet = bytes.fromhex("F0 DC 01 00 01 00 01 00 01")

        self.assertFalse(self.backend.send_control(packet))

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

    def test_ble_discovery_rejects_same_name_fast_pair_advertisement(self):
        device = SimpleNamespace(
            address="5E:DD:01:86:2F:92",
            name="JBL Tune Buds 2-LE",
        )
        advertisement = SimpleNamespace(
            local_name="JBL Tune Buds 2-LE",
            service_uuids=["0000fe2c-0000-1000-8000-00805f9b34fb"],
            manufacturer_data={},
        )

        self.assertFalse(
            BLEController._matches_target_device(
                device, advertisement, "JBL TUNE BUDS 2", ""
            )
        )

    def test_ble_discovery_accepts_harman_service_advertisement(self):
        device = SimpleNamespace(
            address="63:E7:F7:E4:E3:89",
            name="JBL Tune Buds 2-LE",
        )
        advertisement = SimpleNamespace(
            local_name="JBL Tune Buds 2-LE",
            service_uuids=[HARMAN_SERVICE_UUID.upper()],
            manufacturer_data={},
        )

        self.assertTrue(
            BLEController._matches_target_device(
                device, advertisement, "JBL TUNE BUDS 2", ""
            )
        )

    def test_ble_discovery_accepts_harman_advertising_service(self):
        device = SimpleNamespace(
            address="63:E7:F7:E4:E3:89",
            name="JBL Tune Buds 2-LE",
        )
        advertisement = SimpleNamespace(
            local_name="JBL Tune Buds 2-LE",
            service_uuids=[HARMAN_ADVERTISING_SERVICE_UUID],
            service_data={},
            manufacturer_data={},
        )

        self.assertTrue(
            BLEController._matches_target_device(
                device, advertisement, "JBL TUNE BUDS 2", "50:1B:6A:21:A4:3E"
            )
        )

    def test_ble_discovery_accepts_harman_service_data(self):
        device = SimpleNamespace(
            address="63:E7:F7:E4:E3:89",
            name="JBL Tune Buds 2-LE",
        )
        advertisement = SimpleNamespace(
            local_name="JBL Tune Buds 2-LE",
            service_uuids=[],
            service_data={HARMAN_ADVERTISING_SERVICE_UUID: b"\x0c\x21"},
            manufacturer_data={},
        )

        self.assertTrue(
            BLEController._matches_target_device(
                device, advertisement, "JBL TUNE BUDS 2", ""
            )
        )


if __name__ == "__main__":
    unittest.main()
