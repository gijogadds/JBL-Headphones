import struct
import unittest

from core.device_registry import DeviceModel, DeviceRegistry
from core.equalizer import identify_eq_preset
from core.protocol import (
    AncMode,
    Protocol3GroupPacketAssembler,
    Protocol3Handler,
    Protocol4Handler,
    Protocol4PacketAssembler,
)


class Protocol3Tests(unittest.TestCase):
    def test_equalizer_response_keeps_named_preset_selection(self):
        self.assertEqual(identify_eq_preset(1, []), 0)
        self.assertEqual(identify_eq_preset(13, []), 6)
        self.assertEqual(identify_eq_preset(103, [0.0] * 10), 7)

    def test_equalizer_response_matches_preset_gains_without_category(self):
        gains = [4.0, 2.0, 1.0, 2.5, -1.5, -1.5, 0.0, 1.0, 2.0, 4.0]

        self.assertEqual(identify_eq_preset(None, gains), 0)
        self.assertEqual(identify_eq_preset(202, gains), 0)
        self.assertEqual(identify_eq_preset(None, [0.0] * 10), 7)
        self.assertEqual(identify_eq_preset(202, [0.0] * 10), 7)

    def test_battery_query_uses_status_subcommand(self):
        self.assertEqual(Protocol3Handler.REQ_BATTERY_INFO, bytes.fromhex("AA 25 01 01"))

    def test_tune_buds_2_device_info_commands_match_command3_layout(self):
        self.assertEqual(
            Protocol3Handler.build_command3_get([0x000B, 0x000D]),
            bytes.fromhex("AA 06 05 00 01 00 0B 00 0D"),
        )
        self.assertEqual(
            Protocol3Handler.set_auto_power_off_gen3(30, True),
            bytes.fromhex("AA 06 07 00 00 00 0B 03 01 1E 00"),
        )
        self.assertEqual(
            Protocol3Handler.set_auto_power_off_gen3(0, False),
            bytes.fromhex("AA 06 07 00 00 00 0B 03 00 00 00"),
        )

    def test_parses_tune_buds_2_command3_device_info(self):
        packet = bytes.fromhex(
            "AA 06 0C 00 02 "
            "00 0B 03 01 1E 00 "
            "00 0D 02 01 02"
        )

        parsed = Protocol3Handler.parse_packet(packet)

        self.assertTrue(parsed["auto_off_enabled"])
        self.assertEqual(parsed["auto_off_minutes"], 30)
        self.assertTrue(parsed["voice_aware_enabled"])
        self.assertEqual(parsed["voice_aware_level"], 2)

    def test_extracts_command3_frames_using_16_bit_length(self):
        packet = bytes.fromhex("AA 06 03 00 01 00 0B")
        buffer = bytearray(packet)

        self.assertEqual(Protocol3Handler.extract_packets(buffer), [packet])
        self.assertEqual(buffer, b"")

    def test_tune_buds_2_smart_switch_uses_smart_switch_cmd_format(self):
        self.assertEqual(
            Protocol3Handler.REQ_SMART_SWITCH_GEN3,
            bytes.fromhex("AA 80 01 01"),
        )
        self.assertEqual(
            Protocol3Handler.set_smart_audio_video_gen3("audio"),
            bytes.fromhex("AA 80 09 00 00 01 35 00 82 00 E6 00"),
        )
        response = bytes.fromhex("AA 80 09 02 00 01 35 00 82 00 E6 00")

        parsed = Protocol3Handler.parse_packet(response)

        self.assertEqual(parsed["smart_switch_aac"], 256)
        self.assertEqual(parsed["smart_switch_sbc"], 53)
        self.assertEqual(parsed["smart_audio_video_mode"], "audio")

    def test_tune_buds_2_voice_aware_includes_subcommand_and_enabled_state(self):
        self.assertEqual(
            Protocol3Handler.set_voice_aware_gen3(2),
            bytes.fromhex("AA 98 03 00 02 01"),
        )
        self.assertEqual(
            Protocol3Handler.set_voice_aware_gen3(0),
            bytes.fromhex("AA 98 03 00 00 00"),
        )
        self.assertEqual(
            Protocol3Handler.set_voice_aware(2),
            bytes.fromhex("AA 98 01 02"),
        )

    def test_find_my_buds_uses_official_per_ear_enums(self):
        self.assertEqual(
            Protocol3Handler.set_find_my_buds(True, False),
            [bytes.fromhex("AA 36 01 11")],
        )
        self.assertEqual(
            Protocol3Handler.set_find_my_buds(True, True),
            [bytes.fromhex("AA 36 01 11"), bytes.fromhex("AA 36 01 10")],
        )
        self.assertEqual(
            Protocol3Handler.set_find_my_buds(False, False),
            [bytes.fromhex("AA 36 01 01"), bytes.fromhex("AA 36 01 00")],
        )

    def test_tune_buds_2_presets_use_complete_eqsettings2_payload(self):
        packet = Protocol3Handler.build_eq2_packet(
            [1.0] * 10,
            preset_id=4,
        )

        self.assertEqual(packet[:6], bytes.fromhex("AA A2 74 00 03 06"))
        self.assertEqual(len(packet), 120)

    def test_eqsettings2_request_and_response_use_official_layout(self):
        request = Protocol3Handler.request_eq_settings2(255)
        self.assertEqual(request, bytes.fromhex("AA A2 02 01 FF"))
        self.assertEqual(
            Protocol3Handler.extract_packets(bytearray(request)),
            [request],
        )
        response = bytearray(
            Protocol3Handler.build_eq2_packet(
                [float(index) for index in range(10)],
                preset_id=7,
            )
        )
        response[4] = 0x04

        parsed = Protocol3Handler.parse_packet(bytes(response))

        self.assertEqual(parsed["eq_category"], 103)
        self.assertEqual(parsed["eq_gains"], [float(index) for index in range(10)])

    def test_eqsettings2_response_identifies_the_selected_named_preset(self):
        response = bytearray(
            Protocol3Handler.build_eq2_packet(
                [4.0, 2.0, 1.0, 2.5, -1.5, -1.5, 0.0, 1.0, 2.0, 4.0],
                preset_id=0,
            )
        )
        response[4] = 0x04

        parsed = Protocol3Handler.parse_packet(bytes(response))

        self.assertEqual(parsed["eq_category"], 1)
        self.assertEqual(
            identify_eq_preset(parsed["eq_category"], parsed["eq_gains"]),
            0,
        )

    def test_reassembles_fragmented_protocol3_eq_response(self):
        response = bytearray(
            Protocol3Handler.build_eq2_packet([0.0] * 10, preset_id=7)
        )
        response[4] = 0x04
        fragments = Protocol3Handler.fragment_packet(bytes(response), chunk_size=5)
        assembler = Protocol3GroupPacketAssembler()
        complete = None

        for fragment in reversed(fragments):
            complete = assembler.feed(fragment) or complete

        self.assertEqual(complete, bytes(response))
        self.assertEqual(
            Protocol3Handler.parse_packet(complete)["eq_category"],
            103,
        )

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

    def test_parses_captured_tune_buds_2_battery_response(self):
        packet = bytes.fromhex(
            "AA 25 0D 01 00 00 64 5A 00 4B BF 10 B7 10 4E 0C"
        )

        parsed = Protocol3Handler.parse_packet(packet)

        self.assertEqual(
            (parsed["battery_left"], parsed["battery_right"], parsed["battery_case"]),
            (100, 90, 75),
        )

    def test_parses_captured_anc_notification(self):
        packet = bytes.fromhex("AA 91 07 12 01 01 02 00 03 00")

        self.assertEqual(
            Protocol3Handler.parse_packet(packet)["anc_mode"],
            AncMode.ANC,
        )
        self.assertEqual(
            Protocol3Handler.parse_packet(bytes.fromhex("AA 91 01 13"))["anc_mode"],
            AncMode.OFF,
        )

    def test_device_info_response_does_not_misread_metadata_as_battery(self):
        packet = bytes.fromhex(
            "AA 12 25 4A 42 4C 20 54 75 6E 65 20 42 75 64 73 20 32 00 "
            "0C 21 01 64 3E A4 21 6A 1B 50 04 09 00 64 5A BF 10 B7 10 03 00"
        )

        parsed = Protocol3Handler.parse_packet(packet)

        self.assertEqual(parsed["device_name"], "JBL Tune Buds 2")
        self.assertEqual(parsed["pid"], "210C")
        self.assertNotIn("battery_left", parsed)
        self.assertNotIn("battery_right", parsed)
        self.assertNotIn("battery_case", parsed)

    def test_harman_product_id_bytes_are_decoded_little_endian(self):
        parsed = {}

        Protocol3Handler._extract_harman_feature(parsed, 4, bytes.fromhex("0C 21"))

        self.assertEqual(parsed["pid"], "210C")

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
        tune_buds_2 = registry.find_by_pid("210c")

        self.assertEqual(default.protocol_version, 3)
        self.assertIsNotNone(tour_pro_3)
        self.assertEqual(tour_pro_3.protocol_version, 4)
        self.assertIsNotNone(tune_buds_2)
        self.assertTrue(tune_buds_2.uses_harman_ble_gen3_profile)


if __name__ == "__main__":
    unittest.main()
