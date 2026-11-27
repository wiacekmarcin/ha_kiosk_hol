import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kiosk.ntp import DEFAULT_SERVER, NTP_EPOCH, NtpClock, _offset_from_packet


class NtpClockTests(unittest.TestCase):
    def test_offset_uses_transmit_timestamp_and_round_trip_midpoint(self):
        packet = bytearray(48)
        packet[1] = 2
        struct.pack_into("!II", packet, 40, NTP_EPOCH + 1_700_000_005, 0)
        self.assertAlmostEqual(_offset_from_packet(bytes(packet), 1_700_000_000, 1_700_000_002), 4)

    def test_invalid_or_unsynchronized_response_is_rejected(self):
        with self.assertRaisesRegex(OSError, "shorter"):
            _offset_from_packet(b"short", 0, 0)
        packet = bytearray(48)
        with self.assertRaisesRegex(OSError, "unsynchronized"):
            _offset_from_packet(bytes(packet), 0, 0)

    def test_center_server_setting_accepts_hostname_and_rejects_url(self):
        clock = NtpClock()
        self.assertEqual(clock.server, DEFAULT_SERVER)
        self.assertTrue(clock.set_server("ntp.home.arpa"))
        self.assertEqual(clock.server, "ntp.home.arpa")
        with self.assertLogs("kiosk.ntp", level="ERROR"):
            self.assertFalse(clock.set_server("https://ntp.home.arpa"))
        self.assertEqual(clock.server, "ntp.home.arpa")


if __name__ == "__main__":
    unittest.main()
