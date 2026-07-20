from __future__ import annotations

import unittest

from scripts.verify_balancedocket_video import (
    parse_loudness,
    validate_loudness,
    validate_probe,
)


class BalanceDocketVideoVerifierTests(unittest.TestCase):
    @staticmethod
    def _valid_probe() -> dict:
        return {
            "format": {"duration": "172.005167"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "pix_fmt": "yuv420p",
                    "r_frame_rate": "24000/1001",
                    "color_space": "bt709",
                    "color_transfer": "bt709",
                    "color_primaries": "bt709",
                    "nb_read_frames": "4124",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                },
            ],
        }

    def test_accepts_expected_delivery_metadata(self) -> None:
        duration, frames, errors = validate_probe(self._valid_probe())

        self.assertAlmostEqual(172.005167, duration)
        self.assertEqual(4124, frames)
        self.assertEqual((), errors)

    def test_rejects_overlength_and_missing_audio(self) -> None:
        payload = self._valid_probe()
        payload["format"]["duration"] = "180.0"
        payload["streams"] = payload["streams"][:1]

        _, _, errors = validate_probe(payload)

        self.assertTrue(any("not below 180" in error for error in errors))
        self.assertIn("audio stream is missing", errors)

    def test_parses_and_validates_ebur128_summary(self) -> None:
        output = """
Integrated loudness:
  I:         -16.2 LUFS
True peak:
  Peak:       -1.3 dBFS
"""
        loudness, peak = parse_loudness(output)

        self.assertEqual(-16.2, loudness)
        self.assertEqual(-1.3, peak)
        self.assertEqual((), validate_loudness(loudness, peak))

    def test_rejects_silent_or_hot_audio(self) -> None:
        self.assertTrue(validate_loudness(None, None))
        errors = validate_loudness(-12.0, -0.2)
        self.assertTrue(any("outside" in error for error in errors))
        self.assertTrue(any("ceiling" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
