from __future__ import annotations

import argparse
import os
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_closeproof_guarded import (
    LaunchError,
    _canonical_output_path,
    _exclusive_launch_locks,
    _print_launch_summary,
    _require_supported_python,
    _reserve_loopback_port,
    _run,
)
from accounting_agent.closeproof.case import (
    OUTPUT_OWNER_FILENAME,
    build_closeproof_demo,
)


class CloseProofLauncherTests(unittest.TestCase):
    def test_direct_script_entrypoint_can_import_the_repository_package(self) -> None:
        with tempfile.TemporaryDirectory() as output, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/run_closeproof_guarded.py",
                    "--output",
                    str(Path(output) / "demo"),
                    "--port",
                    str(port),
                    "--web-root",
                    "plugins/closeproof/assets/web",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(1, result.returncode)
        self.assertIn("already in use", result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_launch_lock_rejects_a_second_process(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            lock = Path(output) / "demo.run.lock"
            child = """
import sys
from pathlib import Path
from scripts.run_closeproof_guarded import LaunchError, _exclusive_launch_locks

try:
    with _exclusive_launch_locks([Path(sys.argv[1])]):
        raise SystemExit(0)
except LaunchError:
    raise SystemExit(73)
"""
            with _exclusive_launch_locks([lock]):
                result = subprocess.run(
                    [sys.executable, "-c", child, str(lock)],
                    check=False,
                )

            self.assertEqual(73, result.returncode)
            self.assertEqual(0o600, stat.S_IMODE(lock.stat().st_mode))

    def test_launch_lock_rejects_symlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            sentinel = Path(output) / "sentinel"
            sentinel.write_text("do not touch", encoding="utf-8")
            sentinel.chmod(0o644)
            lock = Path(output) / "demo.run.lock"
            lock.symlink_to(sentinel)

            with self.assertRaisesRegex(LaunchError, "regular file"):
                with _exclusive_launch_locks([lock]):
                    self.fail("a symlinked lock must not be opened")

            self.assertEqual("do not touch", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(0o644, stat.S_IMODE(sentinel.stat().st_mode))

    def test_launch_lock_rejects_hardlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            sentinel = Path(output) / "sentinel"
            sentinel.write_text("do not touch", encoding="utf-8")
            sentinel.chmod(0o644)
            lock = Path(output) / "demo.run.lock"
            os.link(sentinel, lock)

            with self.assertRaisesRegex(LaunchError, "regular file"):
                with _exclusive_launch_locks([lock]):
                    self.fail("a multiply linked lock must not be opened")

            self.assertEqual("do not touch", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(0o644, stat.S_IMODE(sentinel.stat().st_mode))

    def test_port_check_rejects_an_existing_listener(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]

            with self.assertRaisesRegex(LaunchError, "already in use"):
                with _reserve_loopback_port(port):
                    self.fail("an occupied port must not be reserved")

    def test_output_aliases_share_one_canonical_lock_target(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            real_output = Path(output) / "real-output"
            real_output.mkdir()
            alias_output = Path(output) / "alias-output"
            alias_output.symlink_to(real_output, target_is_directory=True)

            self.assertEqual(
                _canonical_output_path(str(real_output)),
                _canonical_output_path(str(alias_output)),
            )

    def test_nonempty_unowned_output_is_rejected_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            output_path = Path(output) / "unrelated"
            output_path.mkdir()
            names = (
                "case.json",
                "manifest.json",
                "invoice_INV-4821.pdf",
                "decision-events.jsonl",
                "decision-events.jsonl.head.json",
            )
            for name in names:
                (output_path / name).write_text(f"sentinel:{name}", encoding="utf-8")

            with self.assertRaisesRegex(LaunchError, "owned CloseProof"):
                _canonical_output_path(str(output_path))

            for name in names:
                self.assertEqual(
                    f"sentinel:{name}",
                    (output_path / name).read_text(encoding="utf-8"),
                )

    def test_managed_output_rejects_symlinked_children(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            output_path = Path(output) / "demo"
            build_closeproof_demo(output_dir=output_path)
            sentinel = Path(output) / "sentinel.json"
            sentinel.write_text("do not overwrite", encoding="utf-8")
            case_path = output_path / "case.json"
            case_path.unlink()
            case_path.symlink_to(sentinel)

            with self.assertRaisesRegex(LaunchError, "regular file"):
                _canonical_output_path(str(output_path))

            self.assertEqual("do not overwrite", sentinel.read_text(encoding="utf-8"))

    def test_managed_output_rejects_hardlinked_children(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            output_path = Path(output) / "demo"
            build_closeproof_demo(output_dir=output_path)
            sentinel = Path(output) / "sentinel.lock"
            sentinel.write_text("do not touch", encoding="utf-8")
            sentinel.chmod(0o644)
            managed_lock = output_path / "decision-events.jsonl.lock"
            managed_lock.unlink()
            os.link(sentinel, managed_lock)

            with self.assertRaisesRegex(LaunchError, "regular file"):
                _canonical_output_path(str(output_path))

            self.assertEqual("do not touch", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(0o644, stat.S_IMODE(sentinel.stat().st_mode))

    def test_owner_marker_does_not_authorize_unrelated_case_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            output_path = Path(output) / "demo"
            build_closeproof_demo(output_dir=output_path)
            case_path = output_path / "case.json"
            case_path.write_text('{"sentinel":"do not overwrite"}\n', encoding="utf-8")

            with self.assertRaisesRegex(LaunchError, "owned CloseProof"):
                _canonical_output_path(str(output_path))

            self.assertEqual(
                '{"sentinel":"do not overwrite"}\n',
                case_path.read_text(encoding="utf-8"),
            )

    def test_demo_output_directory_is_private_even_with_permissive_umask(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            output_path = Path(output) / "demo"
            previous_umask = os.umask(0)
            try:
                build_closeproof_demo(output_dir=output_path)
            finally:
                os.umask(previous_umask)

            self.assertEqual(0o700, stat.S_IMODE(output_path.stat().st_mode))

    def test_legacy_managed_output_is_adopted_and_marked(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            output_path = Path(output) / "demo"
            build_closeproof_demo(output_dir=output_path)
            (output_path / OUTPUT_OWNER_FILENAME).unlink()

            _canonical_output_path(str(output_path))
            build_closeproof_demo(output_dir=output_path)

            self.assertTrue((output_path / OUTPUT_OWNER_FILENAME).is_file())

    def test_python_version_is_rejected_before_launch_work(self) -> None:
        with self.assertRaisesRegex(LaunchError, "Python 3.11 or newer"):
            _require_supported_python((3, 10, 14))
        _require_supported_python((3, 11, 0))

    def test_launch_summary_reports_resolved_state_and_advisory_paths(self) -> None:
        output = Path("/tmp/closeproof-demo-4187")

        with patch("builtins.print") as print_mock:
            _print_launch_summary(output=output, port=4187, build_source=False)

        print_mock.assert_any_call(
            "CloseProof is starting at http://127.0.0.1:4187",
            flush=True,
        )
        print_mock.assert_any_call(
            "CloseProof state directory: /tmp/closeproof-demo-4187",
            flush=True,
        )
        print_mock.assert_any_call(
            "CloseProof advisory case: /tmp/closeproof-demo-4187/case.json",
            flush=True,
        )

    def test_source_build_failure_preserves_existing_decision_state(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            output_path = Path(output) / "demo"
            build_closeproof_demo(output_dir=output_path)
            events = output_path / "decision-events.jsonl"
            events.write_text("sentinel decision event\n", encoding="utf-8")
            args = argparse.Namespace(
                output=str(output_path),
                port=4198,
                web_root=str(Path(output) / "dist"),
                build_source=True,
            )

            with (
                patch(
                    "scripts.run_closeproof_guarded.shutil.which",
                    return_value="/fake/npm",
                ),
                patch(
                    "scripts.run_closeproof_guarded.subprocess.run",
                    side_effect=subprocess.CalledProcessError(1, ["npm", "ci"]),
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                _run(args)

            self.assertEqual(
                "sentinel decision event\n",
                events.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
