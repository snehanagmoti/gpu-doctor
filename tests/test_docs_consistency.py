"""The man page, bash completion and README must not drift from the real CLI."""

import re
from pathlib import Path

from gpudoctor import __version__
from gpudoctor.checks import ALL_CHECKS
from gpudoctor.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent


def long_options():
    return {
        opt
        for action in build_parser()._actions
        for opt in action.option_strings
        if opt.startswith("--")
    }


def test_man_page_documents_every_option_and_check():
    man = (ROOT / "docs" / "gpu-doctor.1").read_text().replace("\\-", "-")
    for option in long_options():
        assert option in man, option
    for check in ALL_CHECKS:
        assert f".B {check.id}\n" in man, check.id
    assert f'"gpu-doctor {__version__}"' in man


def test_completion_offers_every_option():
    completion = (ROOT / "completions" / "gpu-doctor").read_text()
    for option in long_options():
        assert re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", completion), option


def test_readme_lists_every_check():
    readme = (ROOT / "README.md").read_text()
    for check in ALL_CHECKS:
        assert f"`{check.id}`" in readme, check.id
