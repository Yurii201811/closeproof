from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.verify_balancedocket_voiceover import TAKES, inspect_directory, inspect_take


class BalanceDocketVoiceoverVerifierTests(unittest.TestCase):
    @staticmethod
    def _write_pcm_wav(
        path: Path,
        *,
        sample_rate: int = 48_000,
        channels: int = 1,
        sample: int = 10_000,
    ) -> None:
        frames = 4_800
        payload = sample.to_bytes(2, "little", signed=True) * frames * channels
        with wave.open(str(path), "wb") as recording:
            recording.setnchannels(channels)
            recording.setsampwidth(2)
            recording.setframerate(sample_rate)
            recording.writeframes(payload)

    def test_accepts_the_complete_expected_mono_48khz_file_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for take in TAKES:
                self._write_pcm_wav(root / take.filename)

            inspections = inspect_directory(root)

        self.assertEqual(8, len(inspections))
        self.assertTrue(all(not item.errors for item in inspections))
        self.assertEqual([take.filename for take in TAKES], [item.take.filename for item in inspections])

    def test_reports_missing_silent_and_wrong_format_takes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_pcm_wav(root / TAKES[0].filename, sample=0)
            self._write_pcm_wav(root / TAKES[1].filename, sample_rate=44_100)
            self._write_pcm_wav(root / TAKES[2].filename, channels=2)

            inspections = inspect_directory(root)

        self.assertIn("recording is silent", inspections[0].errors)
        self.assertTrue(any("48000 Hz" in error for error in inspections[1].errors))
        self.assertTrue(any("expected mono" in error for error in inspections[2].errors))
        self.assertEqual(("file is missing",), inspections[3].errors)

    @patch("scripts.verify_balancedocket_voiceover.subprocess.run")
    @patch("scripts.verify_balancedocket_voiceover.wave.open")
    def test_accepts_extensible_24bit_pcm_wav(
        self,
        wave_open,
        run,
    ) -> None:
        wave_open.side_effect = wave.Error("unknown format: 65534")
        run.side_effect = [
            SimpleNamespace(
                returncode=0,
                stdout=(
                    '{"format":{"duration":"14.5"},"streams":[{'
                    '"codec_type":"audio","codec_name":"pcm_s24le",'
                    '"sample_rate":"48000","channels":1,'
                    '"bits_per_sample":24}]}'
                ),
                stderr="",
            ),
            SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="[Parsed_volumedetect] max_volume: -9.0 dB",
            ),
        ]

        inspection = inspect_take(Path("extensible.wav"), TAKES[0])

        self.assertEqual(24, inspection.sample_width_bits)
        self.assertEqual(-9.0, inspection.peak_dbfs)
        self.assertEqual((), inspection.errors)


if __name__ == "__main__":
    unittest.main()
