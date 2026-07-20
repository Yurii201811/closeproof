#!/usr/bin/env python3
"""Release-gate a final BalanceDocket competition video export."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any


TARGET_DURATION_SECONDS = 180.0
TARGET_FRAME_RATE = Fraction(24_000, 1_001)
TARGET_FRAME_COUNT = 4_124
TARGET_LOUDNESS_RANGE = (-18.0, -14.0)
MAX_TRUE_PEAK_DBFS = -1.0


@dataclass(frozen=True)
class VideoInspection:
    duration_seconds: float
    frame_count: int | None
    integrated_lufs: float | None
    true_peak_dbfs: float | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _stream(payload: dict[str, Any], kind: str) -> dict[str, Any] | None:
    return next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == kind),
        None,
    )


def validate_probe(payload: dict[str, Any]) -> tuple[float, int | None, tuple[str, ...]]:
    errors: list[str] = []
    video = _stream(payload, "video")
    audio = _stream(payload, "audio")

    try:
        duration = float(payload.get("format", {}).get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        errors.append("duration is missing or invalid")
    elif duration >= TARGET_DURATION_SECONDS:
        errors.append(f"duration {duration:.3f}s is not below 180 seconds")

    frame_count: int | None = None
    if video is None:
        errors.append("video stream is missing")
    else:
        if (video.get("width"), video.get("height")) != (1920, 1080):
            errors.append(
                f"expected 1920x1080 video, found "
                f"{video.get('width')}x{video.get('height')}"
            )
        try:
            frame_rate = Fraction(video.get("r_frame_rate", "0/1"))
        except (ValueError, ZeroDivisionError):
            frame_rate = Fraction(0, 1)
        if frame_rate != TARGET_FRAME_RATE:
            errors.append(
                f"expected 24000/1001 fps, found {video.get('r_frame_rate')}"
            )
        if video.get("codec_name") != "h264":
            errors.append(
                f"expected H.264 delivery video, found {video.get('codec_name')}"
            )
        if video.get("pix_fmt") != "yuv420p":
            errors.append(
                f"expected yuv420p delivery pixels, found {video.get('pix_fmt')}"
            )
        color_values = {
            video.get("color_space"),
            video.get("color_transfer"),
            video.get("color_primaries"),
        }
        if color_values != {"bt709"}:
            errors.append("video is not fully tagged as Rec.709")
        raw_frames = video.get("nb_read_frames")
        if raw_frames in {None, "N/A"}:
            errors.append("decoded frame count is unavailable")
        else:
            try:
                frame_count = int(raw_frames)
            except (TypeError, ValueError):
                errors.append(f"invalid frame count: {raw_frames}")
            else:
                if frame_count != TARGET_FRAME_COUNT:
                    errors.append(
                        f"expected {TARGET_FRAME_COUNT} frames, found {frame_count}"
                    )

    if audio is None:
        errors.append("audio stream is missing")
    else:
        if audio.get("codec_name") != "aac":
            errors.append(
                f"expected AAC delivery audio, found {audio.get('codec_name')}"
            )
        try:
            sample_rate = int(audio.get("sample_rate", 0))
        except (TypeError, ValueError):
            sample_rate = 0
        if sample_rate != 48_000:
            errors.append(f"expected 48000 Hz audio, found {sample_rate} Hz")
        if audio.get("channels") not in {1, 2}:
            errors.append(
                f"expected mono or stereo audio, found {audio.get('channels')} channels"
            )

    return duration, frame_count, tuple(errors)


def parse_loudness(output: str) -> tuple[float | None, float | None]:
    loudness_matches = re.findall(
        r"Integrated loudness:\s*\n\s*I:\s*(-?(?:inf|\d+(?:\.\d+)?))\s+LUFS",
        output,
        flags=re.IGNORECASE,
    )
    peak_matches = re.findall(
        r"True peak:\s*\n\s*Peak:\s*(-?(?:inf|\d+(?:\.\d+)?))\s+dBFS",
        output,
        flags=re.IGNORECASE,
    )

    def parse_value(values: list[str]) -> float | None:
        if not values or values[-1].lower() in {"inf", "-inf"}:
            return None
        return float(values[-1])

    return parse_value(loudness_matches), parse_value(peak_matches)


def validate_loudness(
    integrated_lufs: float | None,
    true_peak_dbfs: float | None,
) -> tuple[str, ...]:
    errors: list[str] = []
    if integrated_lufs is None:
        errors.append("integrated loudness could not be measured; audio may be silent")
    elif not TARGET_LOUDNESS_RANGE[0] <= integrated_lufs <= TARGET_LOUDNESS_RANGE[1]:
        errors.append(
            f"integrated loudness {integrated_lufs:.1f} LUFS is outside "
            "the -18 to -14 LUFS delivery range"
        )
    if true_peak_dbfs is None:
        errors.append("true peak could not be measured")
    elif true_peak_dbfs > MAX_TRUE_PEAK_DBFS:
        errors.append(
            f"true peak {true_peak_dbfs:.1f} dBFS exceeds the -1 dBTP ceiling"
        )
    return tuple(errors)


def inspect_video(path: Path) -> VideoInspection:
    if not path.is_file():
        return VideoInspection(0.0, None, None, None, ("file is missing",), ())

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_frames",
            "-show_entries",
            (
                "format=duration:stream=codec_type,codec_name,width,height,pix_fmt,"
                "r_frame_rate,color_space,color_transfer,color_primaries,"
                "nb_read_frames,sample_rate,channels"
            ),
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode:
        return VideoInspection(
            0.0,
            None,
            None,
            None,
            (f"ffprobe failed: {probe.stderr.strip()}",),
            (),
        )

    try:
        payload = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        return VideoInspection(
            0.0,
            None,
            None,
            None,
            (f"ffprobe returned invalid JSON: {exc}",),
            (),
        )

    duration, frame_count, probe_errors = validate_probe(payload)
    errors = list(probe_errors)

    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if decode.returncode:
        errors.append(f"strict full decode failed: {decode.stderr.strip()}")

    integrated_lufs: float | None = None
    true_peak_dbfs: float | None = None
    if _stream(payload, "audio") is not None:
        loudness = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-filter:a",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if loudness.returncode:
            errors.append(f"loudness analysis failed: {loudness.stderr.strip()}")
        else:
            integrated_lufs, true_peak_dbfs = parse_loudness(loudness.stderr)
            errors.extend(validate_loudness(integrated_lufs, true_peak_dbfs))

    return VideoInspection(
        duration,
        frame_count,
        integrated_lufs,
        true_peak_dbfs,
        tuple(errors),
        (),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the final BalanceDocket competition video export."
    )
    parser.add_argument("video", type=Path, help="Final H.264/AAC video file")
    args = parser.parse_args(argv)

    result = inspect_video(args.video)
    state = "PASS" if not result.errors else "FAIL"
    frames = "unknown" if result.frame_count is None else str(result.frame_count)
    loudness = (
        "unavailable"
        if result.integrated_lufs is None
        else f"{result.integrated_lufs:.1f} LUFS"
    )
    peak = (
        "unavailable"
        if result.true_peak_dbfs is None
        else f"{result.true_peak_dbfs:.1f} dBFS"
    )
    print(
        f"{state} {args.video}\n"
        f"     duration={result.duration_seconds:.3f}s frames={frames} "
        f"loudness={loudness} true_peak={peak}"
    )
    for error in result.errors:
        print(f"     ERROR: {error}")
    for warning in result.warnings:
        print(f"     WARN: {warning}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
