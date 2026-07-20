#!/usr/bin/env python3
"""Build one timeline-aligned BalanceDocket narration track from eight takes."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

try:
    from .verify_balancedocket_voiceover import (
        TAKES,
        VoiceoverInspection,
        VoiceoverTake,
        inspect_directory,
        inspect_take,
    )
except ImportError:  # Direct execution: python3 scripts/build_...py
    from verify_balancedocket_voiceover import (  # type: ignore[no-redef]
        TAKES,
        VoiceoverInspection,
        VoiceoverTake,
        inspect_directory,
        inspect_take,
    )

try:
    from .verify_balancedocket_video import parse_loudness, validate_loudness
except ImportError:  # Direct execution: python3 scripts/build_...py
    from verify_balancedocket_video import (  # type: ignore[no-redef]
        parse_loudness,
        validate_loudness,
    )


OUTPUT_DURATION_SECONDS = 172.005167
TARGET_LOUDNESS_LUFS = -16
MAX_TRUE_PEAK_DBFS = -1


def take_start_seconds() -> tuple[float, ...]:
    starts: list[float] = []
    elapsed = 0.0
    for take in TAKES:
        starts.append(elapsed)
        elapsed += take.target_seconds
    return tuple(starts)


def validate_for_assembly(
    inspections: Sequence[VoiceoverInspection],
) -> tuple[str, ...]:
    errors: list[str] = []
    if len(inspections) != len(TAKES):
        return (f"expected {len(TAKES)} inspections, found {len(inspections)}",)

    for expected, inspection in zip(TAKES, inspections, strict=True):
        if inspection.take != expected:
            errors.append(
                f"expected {expected.filename}, found {inspection.take.filename}"
            )
        for error in inspection.errors:
            errors.append(f"{inspection.take.filename}: {error}")
        if inspection.duration_seconds > inspection.take.target_seconds:
            errors.append(
                f"{inspection.take.filename}: duration "
                f"{inspection.duration_seconds:.3f}s exceeds its "
                f"{inspection.take.target_seconds:.0f}s picture window"
            )
    return tuple(errors)


def build_filter_complex(
    inspections: Sequence[VoiceoverInspection],
    measurement: dict[str, str] | None = None,
) -> str:
    starts = take_start_seconds()
    filters: list[str] = []
    labels: list[str] = []

    for index, (inspection, start) in enumerate(
        zip(inspections, starts, strict=True)
    ):
        duration = inspection.duration_seconds
        fade_duration = min(0.03, duration / 2)
        fade_out_start = max(0.0, duration - fade_duration)
        delay_ms = round(start * 1_000)
        label = f"take{index}"
        filters.append(
            f"[{index}:a:0]"
            "aformat=sample_rates=48000:channel_layouts=mono,"
            "asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade_duration:.6f},"
            f"afade=t=out:st={fade_out_start:.6f}:d={fade_duration:.6f},"
            f"adelay=delays={delay_ms}:all=1"
            f"[{label}]"
        )
        labels.append(f"[{label}]")

    filters.append(
        "".join(labels)
        + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0,"
        + f"apad=whole_dur={OUTPUT_DURATION_SECONDS:.6f},"
        + f"atrim=duration={OUTPUT_DURATION_SECONDS:.6f}[aligned]"
    )
    loudnorm = (
        f"loudnorm=I={TARGET_LOUDNESS_LUFS}:"
        f"TP={MAX_TRUE_PEAK_DBFS}:LRA=7"
    )
    if measurement is None:
        loudnorm += ":print_format=json"
    else:
        loudnorm += (
            f":measured_I={measurement['input_i']}"
            f":measured_TP={measurement['input_tp']}"
            f":measured_LRA={measurement['input_lra']}"
            f":measured_thresh={measurement['input_thresh']}"
            f":offset={measurement['target_offset']}"
            ":linear=true:print_format=summary"
        )
    filters.append(f"[aligned]{loudnorm},aresample=48000[narration]")
    return ";".join(filters)


def parse_loudnorm_measurement(output: str) -> dict[str, str]:
    matches = re.findall(
        r"\{\s*\"input_i\"\s*:.*?\}",
        output,
        flags=re.DOTALL,
    )
    if not matches:
        raise ValueError("loudnorm measurement JSON was not found")
    try:
        payload = json.loads(matches[-1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid loudnorm measurement JSON: {exc}") from exc
    required = (
        "input_i",
        "input_tp",
        "input_lra",
        "input_thresh",
        "target_offset",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"loudnorm measurement is missing: {', '.join(missing)}")
    return {key: str(payload[key]) for key in required}


def build_measurement_command(
    directory: Path,
    inspections: Sequence[VoiceoverInspection],
) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-nostdin"]
    for take in TAKES:
        command.extend(["-i", str(directory / take.filename)])
    command.extend(
        [
            "-filter_complex",
            build_filter_complex(inspections),
            "-map",
            "[narration]",
            "-f",
            "null",
            "-",
        ]
    )
    return command


def build_ffmpeg_command(
    directory: Path,
    output: Path,
    inspections: Sequence[VoiceoverInspection],
    measurement: dict[str, str],
) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    for take in TAKES:
        command.extend(["-i", str(directory / take.filename)])
    command.extend(
        [
            "-filter_complex",
            build_filter_complex(inspections, measurement),
            "-map",
            "[narration]",
            "-c:a",
            "pcm_s24le",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-y",
            str(output),
        ]
    )
    return command


def verify_built_track(path: Path) -> None:
    inspection = inspect_take(
        path,
        VoiceoverTake(
            path.name,
            "Timeline-aligned narration track",
            OUTPUT_DURATION_SECONDS,
        ),
    )
    if inspection.errors:
        raise RuntimeError("; ".join(inspection.errors))
    if abs(inspection.duration_seconds - OUTPUT_DURATION_SECONDS) > 0.002:
        raise RuntimeError(
            f"output duration {inspection.duration_seconds:.6f}s does not match "
            f"{OUTPUT_DURATION_SECONDS:.6f}s"
        )

    result = subprocess.run(
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
    if result.returncode:
        raise RuntimeError(f"output loudness verification failed: {result.stderr.strip()}")
    integrated_lufs, true_peak_dbfs = parse_loudness(result.stderr)
    errors = validate_loudness(integrated_lufs, true_peak_dbfs)
    if errors:
        raise RuntimeError("; ".join(errors))


def build_track(directory: Path, output: Path, *, force: bool = False) -> None:
    inspections = inspect_directory(directory)
    errors = validate_for_assembly(inspections)
    if errors:
        raise ValueError("\n".join(errors))
    if output.exists() and not force:
        raise FileExistsError(f"output already exists: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.stem}.",
            suffix=output.suffix or ".wav",
            dir=output.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)

        measurement_run = subprocess.run(
            build_measurement_command(directory, inspections),
            capture_output=True,
            text=True,
            check=False,
        )
        if measurement_run.returncode:
            detail = measurement_run.stderr.strip() or "unknown ffmpeg failure"
            raise RuntimeError(f"ffmpeg loudness measurement failed: {detail}")
        measurement = parse_loudnorm_measurement(measurement_run.stderr)

        command = build_ffmpeg_command(
            directory,
            temporary_path,
            inspections,
            measurement,
        )
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            detail = result.stderr.strip() or "unknown ffmpeg failure"
            raise RuntimeError(f"ffmpeg failed: {detail}")
        verify_built_track(temporary_path)
        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble eight verified BalanceDocket narration takes into one "
            "timeline-aligned 48 kHz mono WAV for Final Cut."
        )
    )
    parser.add_argument("directory", type=Path, help="Folder containing the takes")
    parser.add_argument("output", type=Path, help="Output narration WAV")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace only the named output file if it already exists",
    )
    args = parser.parse_args(argv)

    try:
        build_track(args.directory, args.output, force=args.force)
    except (FileExistsError, OSError, RuntimeError, ValueError) as exc:
        print(f"Voice-over build failed: {exc}")
        return 1

    print(
        f"Built {args.output}\n"
        f"     duration={OUTPUT_DURATION_SECONDS:.6f}s sample_rate=48000Hz "
        f"channels=1 target={TARGET_LOUDNESS_LUFS} LUFS\n"
        "Import at 00:00:00:00 in the locked Final Cut timeline, then verify "
        "the full video and caption timing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
