"""Tests for the Mayara HALO spoke decoding and URL validation."""
import unittest
from unittest.mock import patch
import io
import json
import mayara_spokes as m


class TestMayara(unittest.TestCase):
    def test_wire_roundtrip(self):
        cls = m._message_class()
        source = cls()
        s = source.spokes.add()
        s.angle = 512
        s.range = 1852
        s.data = bytes([0, 10, 40, 63])
        result = cls()
        result.ParseFromString(source.SerializeToString())
        self.assertEqual(result.spokes[0].angle, 512)
        self.assertEqual(result.spokes[0].range, 1852)
        self.assertEqual(result.spokes[0].data, bytes([0, 10, 40, 63]))

    def test_websocket_url_uses_configured_host(self):
        actual = m.spoke_url(
            "http://127.0.0.1:6502", "radar1",
            {"spokeDataUrl": "ws://localhost:6502" + m.API_PATH + "/radar1/spokes"},
        )
        self.assertEqual(actual, "ws://127.0.0.1:6502" + m.API_PATH + "/radar1/spokes")

    def test_reject_unexpected_spoke_path(self):
        with self.assertRaises(ValueError):
            m.spoke_url("http://localhost:6502", "r1",
                        {"spokeDataUrl": "ws://localhost:6502/not-a-spoke-stream"})

    @patch("mayara_spokes.urllib.request.urlopen")
    def test_discover_wrapped_and_unwrapped(self, fetch):
        for wrapped in (True, False):
            records = {"r1": {"name": "HALO 20+", "spokeDataUrl": "/test"}}
            discovery = {"radars": records} if wrapped else records
            fetch.side_effect = [
                io.BytesIO(json.dumps(discovery).encode()),
                io.BytesIO(json.dumps({"spokesPerRevolution": 2048}).encode()),
            ]
            radar_id, info, caps = m.discover("http://localhost:6502")
            self.assertEqual(radar_id, "r1")
            self.assertEqual(info["name"], "HALO 20+")
            self.assertEqual(caps["spokesPerRevolution"], 2048)


if __name__ == "__main__":
    unittest.main()
