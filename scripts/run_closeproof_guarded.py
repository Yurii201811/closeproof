#!/usr/bin/env python3
"""Hold output and port locks for the complete CloseProof demo lifetime."""

from __future__ import annotations

import argparse
import fcntl
import os
import shutil
import socket
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


# Executing this file directly makes ``scripts/`` Python's import root. Add the
# repository root explicitly so the guarded shell launchers work from a fresh
# checkout without requiring an editable install or PYTHONPATH configuration.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class LaunchError(RuntimeError):
    """Raised before any demo state is regenerated."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--web-root", required=True)
    parser.add_argument("--build-source", action="store_true")
    return parser


@contextmanager
def _exclusive_launch_locks(paths: list[Path]) -> Iterator[tuple[int, ...]]:
    descriptors: list[tuple[Path, int]] = []
    try:
        for path in sorted(set(paths), key=lambda item: str(item.absolute())):
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = _open_regular_lock_file(path)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                os.close(descriptor)
                raise LaunchError(
                    "CloseProof cannot start: another launcher owns this output or port; "
                    "existing demo state was not reset"
                ) from exc
            descriptors.append((path, descriptor))
        yield tuple(descriptor for _path, descriptor in descriptors)
    finally:
        for _path, descriptor in reversed(descriptors):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _open_regular_lock_file(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LaunchError("CloseProof lock path must be a regular file") from exc
    try:
        opened = os.fstat(descriptor)
        linked = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(linked.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino)
        ):
            raise LaunchError("CloseProof lock path must be a regular file")
        os.fchmod(descriptor, 0o600)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


@contextmanager
def _reserve_loopback_port(port: int) -> Iterator[socket.socket]:
    if not 1 <= port <= 65535:
        raise LaunchError("CLOSEPROOF_PORT must be an integer from 1 through 65535")
    with socket.socket() as reservation:
        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            reservation.bind(("127.0.0.1", port))
        except OSError as exc:
            raise LaunchError(
                f"CloseProof cannot start: 127.0.0.1:{port} is already in use; "
                "existing demo state was not reset"
            ) from exc
        yield reservation


def _canonical_output_path(raw_output: str) -> Path:
    output = Path(raw_output).expanduser().resolve(strict=False)
    if output == Path(output.anchor) or output == Path.cwd().resolve():
        raise LaunchError("CLOSEPROOF_OUTPUT must name a dedicated demo directory")
    if output.exists() and not output.is_dir():
        raise LaunchError("CLOSEPROOF_OUTPUT must name a directory")
    try:
        from accounting_agent.closeproof.case import (
            validate_closeproof_output_directory,
        )

        validate_closeproof_output_directory(output)
    except ValueError as exc:
        raise LaunchError(str(exc)) from exc
    return output


def _require_supported_python(version_info=None) -> None:
    version = version_info or sys.version_info
    if tuple(version[:2]) < (3, 11):
        found = ".".join(str(part) for part in version[:3])
        raise LaunchError(
            f"CloseProof requires Python 3.11 or newer; found Python {found}"
        )


def _print_launch_summary(
    *, output: Path, port: int, build_source: bool
) -> None:
    print(f"CloseProof is starting at http://127.0.0.1:{port}", flush=True)
    print(f"CloseProof state directory: {output}", flush=True)
    print(f"CloseProof advisory case: {output / 'case.json'}", flush=True)
    if build_source:
        print("Press Ctrl-C to stop the local-only reviewer.", flush=True)
    else:
        print(
            "This path uses the checked-in web bundle; Node.js and rebuilding are not required.",
            flush=True,
        )


def _run(args: argparse.Namespace) -> int:
    _require_supported_python()
    output = _canonical_output_path(args.output)
    web_root = Path(args.web_root).resolve(strict=False)
    if not web_root.joinpath("index.html").is_file() and not args.build_source:
        raise LaunchError("The checked-in CloseProof web bundle is missing")

    npm = shutil.which("npm") if args.build_source else None
    if args.build_source and npm is None:
        raise LaunchError("The source-build route requires npm on PATH")

    lock_paths = [
        Path(f"{output}.run.lock"),
        Path(".local/closeproof-runtime-locks") / f"port-{args.port}.lock",
    ]
    if args.build_source:
        lock_paths.append(
            Path(".local/closeproof-runtime-locks/frontend-source-build.lock")
        )

    with _exclusive_launch_locks(lock_paths) as lock_descriptors:
        with _reserve_loopback_port(args.port) as reservation:
            if args.build_source:
                assert npm is not None
                subprocess.run([npm, "--prefix", "apps/closeproof-web", "ci"], check=True)
                subprocess.run(
                    [npm, "--prefix", "apps/closeproof-web", "run", "build"],
                    check=True,
                )
                if not web_root.joinpath("index.html").is_file():
                    raise LaunchError("The source build did not produce CloseProof web assets")

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "closeproof-demo",
                    "--output",
                    str(output),
                ],
                check=True,
            )

            for descriptor in lock_descriptors:
                os.set_inheritable(descriptor, True)
            os.set_inheritable(reservation.fileno(), True)

            _print_launch_summary(
                output=output,
                port=args.port,
                build_source=args.build_source,
            )
            os.execv(
                sys.executable,
                [
                    sys.executable,
                    "-m",
                    "accounting_agent.cli",
                    "closeproof-serve",
                    "--case",
                    str(output / "case.json"),
                    "--events",
                    str(output / "decision-events.jsonl"),
                    "--web",
                    str(web_root),
                    "--port",
                    str(args.port),
                    "--socket-fd",
                    str(reservation.fileno()),
                ],
            )
    return 1


def main() -> int:
    try:
        return _run(_parser().parse_args())
    except LaunchError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except OSError:
        print("CloseProof cannot start: local process launch failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
