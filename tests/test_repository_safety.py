from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositorySafetyTests(unittest.TestCase):
    def test_gitignore_blocks_runtime_secrets_and_client_data(self) -> None:
        patterns = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }

        required_patterns = {
            ".local/",
            ".env",
            ".env.*",
            "*.sqlite",
            "*.db",
            "*.jsonl",
            "tokens/",
            "secrets/",
            "credentials/",
            "client_data/",
            "clients/",
            "raw_client_documents/",
            "intake_documents/",
            "approval_packets/",
            "__pycache__/",
            "*.py[cod]",
        }
        self.assertTrue(
            required_patterns.issubset(patterns),
            f"missing ignore patterns: {sorted(required_patterns - patterns)}",
        )


if __name__ == "__main__":
    unittest.main()
