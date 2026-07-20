from __future__ import annotations

import unittest
from pathlib import Path

from scripts.build_balancedocket_voiceover_track import (
    OUTPUT_DURATION_SECONDS,
    build_ffmpeg_command,
    build_filter_complex,
    parse_loudnorm_measurement,
    take_start_seconds,
    validate_for_assembly,
)
from scripts.verify_balancedocket_voiceover import (
    TAKES,
    VoiceoverInspection,
)


class BalanceDocketVoiceoverTrackBuilderTests(unittest.TestCase):
    MEASUREMENT = {
        "input_i": "-22.00",
        "input_tp": "-8.00",
        "input_lra": "3.00",
        "input_thresh": "-32.00",
        "target_offset": "0.10",
    }

    @staticmethod
    def _inspections(
        *,
        duration_adjustments: dict[str, float] | None = None,
        errors: dict[str, tuple[str, ...]] | None = None,
    ) -> tuple[VoiceoverInspection, ...]:
        adjustments = duration_adjustments or {}
        supplied_errors = errors or {}
        return tuple(
            VoiceoverInspection(
                take=take,
                duration_seconds=take.target_seconds
                + adjustments.get(take.filename, -0.5),
                sample_rate=48_000,
                channels=1,
                sample_width_bits=24,
                peak_dbfs=-9.0,
                errors=supplied_errors.get(take.filename, ()),
                warnings=(),
            )
            for take in TAKES
        )

    def test_uses_the_eight_locked_marker_starts(self) -> None:
        self.assertEqual(
            (0.0, 15.0, 34.0, 62.0, 96.0, 120.0, 145.0, 162.0),
            take_start_seconds(),
        )

        filter_complex = build_filter_complex(self._inspections())

        for delay in (0, 15_000, 34_000, 62_000, 96_000, 120_000, 145_000, 162_000):
            self.assertIn(f"adelay=delays={delay}:all=1", filter_complex)
        self.assertIn(f"apad=whole_dur={OUTPUT_DURATION_SECONDS:.6f}", filter_complex)
        self.assertIn("loudnorm=I=-16:TP=-1:LRA=7", filter_complex)
        self.assertIn("print_format=json", filter_complex)

    def test_rejects_invalid_or_overrunning_takes(self) -> None:
        inspections = self._inspections(
            duration_adjustments={TAKES[0].filename: 0.01},
            errors={TAKES[1].filename: ("recording is silent",)},
        )

        errors = validate_for_assembly(inspections)

        self.assertTrue(any("exceeds its 15s picture window" in item for item in errors))
        self.assertIn(f"{TAKES[1].filename}: recording is silent", errors)

    def test_builds_a_non_destructive_final_cut_ready_ffmpeg_command(self) -> None:
        directory = Path("/tmp/voiceover")
        output = Path("/tmp/voiceover/BalanceDocket_voiceover_track.wav")

        command = build_ffmpeg_command(
            directory,
            output,
            self._inspections(),
            self.MEASUREMENT,
        )

        self.assertEqual("ffmpeg", command[0])
        self.assertEqual(8, command.count("-i"))
        self.assertIn("pcm_s24le", command)
        self.assertIn("48000", command)
        self.assertEqual(str(output), command[-1])
        self.assertNotIn("-shortest", command)
        self.assertIn("measured_I=-22.00", command[command.index("-filter_complex") + 1])

    def test_parses_first_pass_loudnorm_measurement(self) -> None:
        payload = """
        [Parsed_loudnorm_0] {
          "input_i" : "-22.00",
          "input_tp" : "-8.00",
          "input_lra" : "3.00",
          "input_thresh" : "-32.00",
          "output_i" : "-16.10",
          "target_offset" : "0.10"
        }
        """

        self.assertEqual(self.MEASUREMENT, parse_loudnorm_measurement(payload))


if __name__ == "__main__":
    unittest.main()
