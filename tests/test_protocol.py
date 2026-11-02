import struct
import unittest

from core.device_registry import DeviceModel, DeviceRegistry
from core.protocol import (
    AncMode,
    Protocol3Handler,
    Protocol4Handler,
    Protocol4PacketAssembler,
)


class Protocol3Tests(unittest.TestCase):
    def test_battery_query_uses_status_subcommand(self):
        self.assertEqual(Protocol3Handler.REQ_BATTERY_INFO, bytes.fromhex("AA 25 01 01"))

    def test_parses_three_byte_tws_battery_response(self):
        packet = bytes.fromhex("AA 25 03 32 C8 64")

        parsed = Protocol3Handler.parse_packet(packet)

        self.assertEqual(parsed["battery_left"], 50)
        self.assertEqual(parsed["charging_left"], False)
        self.assertEqual(parsed["battery_right"], 72)
        self.assertEqual(parsed["charging_right"], True)
        self.assertEqual(parsed["battery_case"], 100)

    def test_parses_full_battery_status_response(self):
        packet = bytes.fromhex("AA 25 05 01 00 01 46 50")

        parsed = Protocol3Handler.parse_packet(packet)

        self.assertEqual(parsed["battery_left"], 70)
        self.assertEqual(parsed["battery_right"], 80)
        self.assertTrue(parsed["charging_right"])

    def test_extracts_fragmented_and_concatenated_rfcomm_frames(self):
        first = bytes.fromhex("AA 25 03 32 40 50")
        second = bytes.fromhex("AA 91 01 13")
        buffer = bytearray(first[:4])

        self.assertEqual(Protocol3Handler.extract_packets(buffer), [])

        buffer.extend(first[4:] + second)
        self.assertEqual(Protocol3Handler.extract_packets(buffer), [first, second])
        self.assertEqual(buffer, b"")


class Protocol4Tests(unittest.TestCase):
    def test_anc_modes_use_status_bit_and_off_round_trips(self):
        expected = {
            AncMode.OFF: (0x00, 0x00, 0x00),
            AncMode.ANC: (0x80, 0x00, 0x00),
            AncMode.AMBIENT_AWARE: (0x00, 0x80, 0x00),
            AncMode.TALKTHRU: (0x00, 0x00, 0x80),
        }

        for mode, value in expected.items():
            with self.subTest(mode=mode):
                packet = Protocol4Handler.set_anc_mode(mode)[0]
                parsed = Protocol4Handler.parse_packet(packet)
                self.assertEqual((packet[10], packet[13], packet[16]), value)
                self.assertEqual(parsed["anc_mode"], mode)

    def test_get_feature_queries_are_fragmented_to_att_payload_size(self):
        ids = list(range(1, 13))
        packets = Protocol4Handler.build_get_features(ids)
        assembler = Protocol4PacketAssembler()
        complete = None

        self.assertTrue(all(len(packet) <= 20 for packet in packets))
        for packet in reversed(packets):
            complete = assembler.feed(packet) or complete

        self.assertIsNotNone(complete)
        self.assertEqual(complete[4:8], bytes.fromhex("01 00 18 00"))
        self.assertEqual(complete[8:], b"".join(fid.to_bytes(2, "little") for fid in ids))

    def test_equalizer_info_parser_reads_band_gains(self):
        info = bytearray(19 + 13 * 2)
        info[0] = 103
        info[2] = 2
        info[19 + 5:19 + 9] = struct.pack("<f", -2.5)
        info[32 + 5:32 + 9] = struct.pack("<f", 4.0)
        payload = (
            Protocol4Handler.FEATURE_EQ_INFO.to_bytes(2, "little")
            + info
        )
        packet = Protocol4Handler.build_packet(
            Protocol4Handler.CMD_GET_DEVICE_INFO, payload
        )[0]

        parsed = Protocol4Handler.parse_packet(packet)

        self.assertEqual(parsed["eq_category"], 103)
        self.assertEqual(parsed["eq_gains"], [-2.5, 4.0])

    def test_eq_curve_packets_fit_minimum_att_mtu(self):
        packets = Protocol4Handler.build_eq_curve_packet([0.0] * 10)

        self.assertGreater(len(packets), 1)
        self.assertTrue(all(len(packet) <= 20 for packet in packets))
        self.assertTrue(all(packet[4] == len(packets) for packet in packets))


class DeviceModelTests(unittest.TestCase):
    def test_protocol_generation_defaults_to_three_and_marks_protocol_four(self):
        default = DeviceModel({"name": "JBL Tune Buds 2", "pid": "210c"}, "")
        registry = DeviceRegistry()
        tour_pro_3 = registry.find_by_pid("20f2")

        self.assertEqual(default.protocol_version, 3)
        self.assertIsNotNone(tour_pro_3)
        self.assertEqual(tour_pro_3.protocol_version, 4)


if __name__ == "__main__":
    unittest.main()
