#!/usr/bin/env python3
"""Preflight the eight human-recorded BalanceDocket voice-over takes."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class VoiceoverTake:
    filename: str
    title: str
    target_seconds: float


@dataclass(frozen=True)
class VoiceoverInspection:
    take: VoiceoverTake
    duration_seconds: float
    sample_rate: int
    channels: int
    sample_width_bits: int
    peak_dbfs: float | None
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


TAKES = (
    VoiceoverTake("01_problem.wav", "Problem and product", 15.0),
    VoiceoverTake("02_baseline.wav", "Codex workflow and local baseline", 19.0),
    VoiceoverTake("03_controls.wav", "Source and deterministic controls", 28.0),
    VoiceoverTake("04_codex.wav", "Real Codex and GPT-5.6 route", 34.0),
    VoiceoverTake("05_advisory.wav", "Validated advisory boundary", 24.0),
    VoiceoverTake("06_decision.wav", "Human decision", 25.0),
    VoiceoverTake("07_workpaper.wav", "Workpaper proof", 17.0),
    VoiceoverTake("08_close.wav", "Build proof and close", 10.0),
)


def _peak_sample(data: bytes, sample_width: int) -> tuple[int, int]:
    if sample_width == 1:
        return max((abs(value - 128) for value in data), default=0), 127
    if sample_width not in {2, 3, 4}:
        return 0, 0

    peak = 0
    for offset in range(0, len(data) - sample_width + 1, sample_width):
        sample = int.from_bytes(
            data[offset : offset + sample_width],
            byteorder="little",
            signed=True,
        )
        peak = max(peak, abs(sample))
    return peak, (1 << (sample_width * 8 - 1)) - 1


def _inspection_from_measurements(
    take: VoiceoverTake,
    *,
    duration: float,
    sample_rate: int,
    channels: int,
    sample_width_bits: int,
    peak_dbfs: float | None,
    format_errors: Iterable[str] = (),
) -> VoiceoverInspection:
    errors = list(format_errors)
    warnings: list[str] = []
    if channels != 1:
        errors.append(f"expected mono, found {channels} channels")
    if sample_rate != 48_000:
        errors.append(f"expected 48000 Hz, found {sample_rate} Hz")
    if sample_width_bits not in {16, 24}:
        errors.append(
            f"expected 16-bit or 24-bit PCM, found {sample_width_bits}-bit"
        )

    if peak_dbfs is None:
        errors.append("recording is silent")
    elif peak_dbfs >= -0.01:
        errors.append("audio reaches digital full scale and may be clipped")
    elif not -12.0 <= peak_dbfs <= -6.0:
        warnings.append(
            f"peak is {peak_dbfs:.1f} dBFS; preferred range is -12 to -6 dBFS"
        )

    if duration > take.target_seconds + 1.25:
        warnings.append(
            f"duration {duration:.2f}s exceeds the {take.target_seconds:.0f}s slot; "
            "trim room tone or retake"
        )
    elif duration < take.target_seconds - 5.0:
        warnings.append(
            f"duration {duration:.2f}s is much shorter than the "
            f"{take.target_seconds:.0f}s slot; confirm no words are missing"
        )

    return VoiceoverInspection(
        take=take,
        duration_seconds=duration,
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bits=sample_width_bits,
        peak_dbfs=peak_dbfs,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def _inspect_extensible_pcm(path: Path, take: VoiceoverTake) -> VoiceoverInspection:
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration:stream=codec_type,codec_name,sample_rate,"
                    "channels,bits_per_sample,bits_per_raw_sample"
                ),
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return VoiceoverInspection(
            take, 0.0, 0, 0, 0, None, (f"ffprobe is unavailable: {exc}",), ()
        )
    if probe.returncode:
        return VoiceoverInspection(
            take,
            0.0,
            0,
            0,
            0,
            None,
            (f"ffprobe failed: {probe.stderr.strip()}",),
            (),
        )

    try:
        payload = json.loads(probe.stdout)
        stream = next(
            item
            for item in payload.get("streams", [])
            if item.get("codec_type") == "audio"
        )
        duration = float(payload.get("format", {}).get("duration", 0.0))
        sample_rate = int(stream.get("sample_rate", 0))
        channels = int(stream.get("channels", 0))
        sample_width_bits = int(
            stream.get("bits_per_sample") or stream.get("bits_per_raw_sample") or 0
        )
        codec = str(stream.get("codec_name", "unknown"))
    except (json.JSONDecodeError, StopIteration, TypeError, ValueError) as exc:
        return VoiceoverInspection(
            take,
            0.0,
            0,
            0,
            0,
            None,
            (f"ffprobe returned invalid PCM metadata: {exc}",),
            (),
        )

    format_errors = []
    if codec not in {"pcm_s16le", "pcm_s24le"}:
        format_errors.append(f"expected uncompressed PCM, found {codec}")

    try:
        peak = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-filter:a",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return VoiceoverInspection(
            take,
            duration,
            sample_rate,
            channels,
            sample_width_bits,
            None,
            (f"ffmpeg is unavailable: {exc}",),
            (),
        )
    if peak.returncode:
        return VoiceoverInspection(
            take,
            duration,
            sample_rate,
            channels,
            sample_width_bits,
            None,
            (f"peak analysis failed: {peak.stderr.strip()}",),
            (),
        )
    match = re.findall(
        r"max_volume:\s*(-?(?:inf|\d+(?:\.\d+)?))\s+dB",
        peak.stderr,
        flags=re.IGNORECASE,
    )
    if not match:
        return VoiceoverInspection(
            take,
            duration,
            sample_rate,
            channels,
            sample_width_bits,
            None,
            ("peak analysis returned no max_volume measurement",),
            (),
        )
    peak_dbfs = None if match[-1].lower() in {"inf", "-inf"} else float(match[-1])
    return _inspection_from_measurements(
        take,
        duration=duration,
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bits=sample_width_bits,
        peak_dbfs=peak_dbfs,
        format_errors=format_errors,
    )


def inspect_take(path: Path, take: VoiceoverTake) -> VoiceoverInspection:
    try:
        with wave.open(str(path), "rb") as recording:
            channels = recording.getnchannels()
            sample_rate = recording.getframerate()
            sample_width = recording.getsampwidth()
            frame_count = recording.getnframes()
            compression = recording.getcomptype()
            data = recording.readframes(frame_count)
    except wave.Error as exc:
        if "unknown format: 65534" in str(exc):
            return _inspect_extensible_pcm(path, take)
        return VoiceoverInspection(
            take=take,
            duration_seconds=0.0,
            sample_rate=0,
            channels=0,
            sample_width_bits=0,
            peak_dbfs=None,
            errors=(f"not a readable PCM WAV: {exc}",),
            warnings=(),
        )
    except (OSError, EOFError) as exc:
        return VoiceoverInspection(
            take=take,
            duration_seconds=0.0,
            sample_rate=0,
            channels=0,
            sample_width_bits=0,
            peak_dbfs=None,
            errors=(f"not a readable PCM WAV: {exc}",),
            warnings=(),
        )

    duration = frame_count / sample_rate if sample_rate else 0.0
    peak, full_scale = _peak_sample(data, sample_width)
    peak_dbfs = None
    format_errors = []
    if compression != "NONE":
        format_errors.append(f"compressed WAV ({compression}); use uncompressed PCM")
    if full_scale <= 0:
        format_errors.append("unsupported sample width")
    elif peak:
        peak_dbfs = 20 * math.log10(peak / full_scale)

    return _inspection_from_measurements(
        take,
        duration=duration,
        sample_rate=sample_rate,
        channels=channels,
        sample_width_bits=sample_width * 8,
        peak_dbfs=peak_dbfs,
        format_errors=format_errors,
    )


def inspect_directory(directory: Path) -> tuple[VoiceoverInspection, ...]:
    inspections: list[VoiceoverInspection] = []
    for take in TAKES:
        path = directory / take.filename
        if not path.is_file():
            inspections.append(
                VoiceoverInspection(
                    take=take,
                    duration_seconds=0.0,
                    sample_rate=0,
                    channels=0,
                    sample_width_bits=0,
                    peak_dbfs=None,
                    errors=("file is missing",),
                    warnings=(),
                )
            )
            continue
        inspections.append(inspect_take(path, take))
    return tuple(inspections)


def _format_messages(messages: Iterable[str]) -> str:
    return "; ".join(messages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the eight BalanceDocket narration WAV files."
    )
    parser.add_argument("directory", type=Path, help="Folder containing the takes")
    args = parser.parse_args(argv)

    inspections = inspect_directory(args.directory)
    for inspection in inspections:
        peak = (
            "silent"
            if inspection.peak_dbfs is None
            else f"{inspection.peak_dbfs:.1f} dBFS"
        )
        state = "ERROR" if inspection.errors else "WARN" if inspection.warnings else "OK"
        print(
            f"{state:5} {inspection.take.filename:<20} "
            f"{inspection.duration_seconds:6.2f}s  {inspection.sample_rate:5d} Hz  "
            f"{inspection.channels} ch  {inspection.sample_width_bits:2d}-bit  {peak}"
        )
        if inspection.errors:
            print(f"      {_format_messages(inspection.errors)}")
        if inspection.warnings:
            print(f"      {_format_messages(inspection.warnings)}")

    failures = sum(bool(inspection.errors) for inspection in inspections)
    warnings = sum(bool(inspection.warnings) for inspection in inspections)
    print(f"Voice-over preflight: {len(inspections) - failures}/8 valid, {warnings} warning(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
