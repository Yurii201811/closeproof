from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STYLES_PATH = REPO_ROOT / "apps" / "closeproof-web" / "src" / "styles.css"
APP_PATH = REPO_ROOT / "apps" / "closeproof-web" / "src" / "App.tsx"


def _relative_luminance(hex_color: str) -> float:
    channels = [
        int(hex_color[index : index + 2], 16) / 255
        for index in (1, 3, 5)
    ]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


class CloseProofFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.styles = STYLES_PATH.read_text(encoding="utf-8")
        cls.app = APP_PATH.read_text(encoding="utf-8")

        root_block = re.search(r":root\s*\{(?P<body>.*?)\}", cls.styles, re.DOTALL)
        if root_block is None:
            raise AssertionError("styles.css must define a :root design-token block")
        cls.colors = dict(
            re.findall(
                r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;",
                root_block.group("body"),
            )
        )

    def test_key_design_tokens_meet_contrast_thresholds(self) -> None:
        text_pairs = {
            ("ink", "paper"),
            ("ink", "paper-raised"),
            ("ink-muted", "paper"),
            ("ink-muted", "paper-raised"),
            ("verified", "paper"),
            ("verified", "verified-soft"),
            ("exception", "paper"),
            ("exception", "exception-soft"),
            ("waiting", "paper"),
            ("waiting", "paper-raised"),
        }
        indicator_pairs = {
            ("focus", "paper"),
            ("focus", "paper-raised"),
            ("rule-strong", "paper"),
            ("rule-strong", "paper-raised"),
        }

        expected_tokens = {token for pair in text_pairs | indicator_pairs for token in pair}
        self.assertEqual(
            set(),
            expected_tokens - self.colors.keys(),
            "all contrast-contract tokens must remain six-digit hex colors",
        )

        for foreground, background in sorted(text_pairs):
            with self.subTest(foreground=foreground, background=background):
                ratio = _contrast_ratio(
                    self.colors[foreground], self.colors[background]
                )
                self.assertGreaterEqual(
                    ratio,
                    4.5,
                    f"--{foreground} on --{background} has {ratio:.2f}:1 contrast",
                )

        for foreground, background in sorted(indicator_pairs):
            with self.subTest(foreground=foreground, background=background):
                ratio = _contrast_ratio(
                    self.colors[foreground], self.colors[background]
                )
                self.assertGreaterEqual(
                    ratio,
                    3.0,
                    f"--{foreground} on --{background} has {ratio:.2f}:1 contrast",
                )

    def test_mobile_layout_breakpoint_matches_between_react_and_css(self) -> None:
        app_breakpoint = re.search(
            r'MOBILE_LAYOUT_QUERY\s*=\s*"\(max-width:\s*(\d+)px\)"',
            self.app,
        )
        self.assertIsNotNone(app_breakpoint, "App.tsx must define MOBILE_LAYOUT_QUERY")
        assert app_breakpoint is not None

        css_breakpoints = {
            int(value)
            for value in re.findall(
                r"@media\s*\(\s*max-width:\s*(\d+)px\s*\)", self.styles
            )
        }
        react_width = int(app_breakpoint.group(1))

        self.assertEqual(1279, react_width)
        self.assertIn(
            react_width,
            css_breakpoints,
            "React and CSS must switch to the mobile layout at the same width",
        )


if __name__ == "__main__":
    unittest.main()
