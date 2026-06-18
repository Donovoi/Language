#!/usr/bin/env python3
"""Validate release-checklist commands against the category runner."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "docs/development/release-checklist.md"
DISPOSABLE_ENV_DOC = ROOT / "docs/development/disposable-test-environments.md"
RUNNER = ROOT / "scripts/run_test_category.py"
CATEGORY_COMMAND_RE = re.compile(
    r"`python(?:3)?\s+scripts/run_test_category\.py\s+([A-Za-z0-9_-]+)(?:\s+[^`]*)?`"
)

REQUIRED_COMMAND_SEQUENCE = (
    "release-status",
    "physical-audio-handoff",
    "release-evidence",
    "release-evidence-score",
    "release",
)
REQUIRED_COMMANDS = {
    "all",
    "contracts",
    "core",
    "physical-audio-handoff",
    "quick",
    "release",
    "release-artifacts",
    "release-evidence",
    "release-evidence-score",
    "release-status",
    "route-triage",
    "smoke-local",
}
REQUIRED_PATTERNS = {
    "listener-ear WAV list": re.compile(
        r"collect or import the three real listener-ear WAVs.*"
        r"source-open-ear-recording\.wav.*"
        r"source-isolated-ear-recording\.wav.*"
        r"translated-headphone-recording\.wav",
        re.DOTALL,
    ),
    "concrete score labels": re.compile(
        r"set concrete .*"
        r"LANGUAGE_HEADPHONE_DEVICE_LABEL.*"
        r"LANGUAGE_ISOLATION_FIXTURE_LABEL.*"
        r"LANGUAGE_MEASUREMENT_MICROPHONE_LABEL",
        re.DOTALL,
    ),
    "fresh route-probe warning": re.compile(
        r"If the report says `STALE-TRIAGE` or `UNRELATED-TRIAGE`, rerun\s+"
        r"`python scripts/run_test_category\.py route-triage`",
        re.DOTALL,
    ),
    "authoritative JSON artifact": re.compile(
        r"keep\s+`artifacts/release/audio-gate-report\.json` as the authoritative pass/fail artifact",
        re.DOTALL,
    ),
    "clean artifact manifest": re.compile(
        r"releasable handoffs must show `dirty_tree: false`",
    ),
}
DISALLOWED_TEXT = (
    "make live-microphone-capture-check",
)
DISALLOWED_DOC_TEXT = {
    DISPOSABLE_ENV_DOC: (
        "placeholder REPLACE_WITH_HEADPHONE_MODEL",
        "placeholder REPLACE_WITH_EARCUP_AND_MIC_POSITION",
        "placeholder REPLACE_WITH_MIC_MODEL_AND_POSITION",
    ),
}


def load_runner_categories() -> set[str]:
    spec = importlib.util.spec_from_file_location("language_run_test_category", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {RUNNER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    categories = getattr(module, "CATEGORIES", None)
    if not isinstance(categories, dict):
        raise RuntimeError("run_test_category.py did not expose CATEGORIES")
    return {str(name) for name in categories}


def command_categories(text: str) -> list[str]:
    return CATEGORY_COMMAND_RE.findall(text)


def positions_for_sequence(text: str, sequence: tuple[str, ...]) -> list[int]:
    positions: list[int] = []
    commands = [(match.group(1), match.start()) for match in CATEGORY_COMMAND_RE.finditer(text)]
    for category in sequence:
        matches = [position for command, position in commands if command == category]
        positions.append(matches[0] if matches else -1)
    return positions


def validate_parser_contract() -> None:
    sample = "\n".join(
        f"- `python scripts/run_test_category.py {category} --runner powershell`"
        for category in REQUIRED_COMMAND_SEQUENCE
    )
    if command_categories(sample) != list(REQUIRED_COMMAND_SEQUENCE):
        raise AssertionError("category command parser should tolerate optional command arguments")
    positions = positions_for_sequence(sample, REQUIRED_COMMAND_SEQUENCE)
    if any(index < 0 for index in positions) or positions != sorted(positions):
        raise AssertionError("ordered release evidence sequence parser should tolerate optional arguments")


def validate() -> None:
    validate_parser_contract()
    text = CHECKLIST.read_text(encoding="utf-8")
    available = load_runner_categories()
    seen = command_categories(text)
    if not seen:
        raise AssertionError("release checklist does not contain category-runner commands")

    unknown = sorted({category for category in seen if category not in available})
    if unknown:
        raise AssertionError(f"release checklist references unknown categories: {unknown}")

    missing = sorted(REQUIRED_COMMANDS.difference(seen))
    if missing:
        raise AssertionError(f"release checklist is missing required category commands: {missing}")

    positions = positions_for_sequence(text, REQUIRED_COMMAND_SEQUENCE)
    if any(index < 0 for index in positions) or positions != sorted(positions):
        raise AssertionError(
            "release checklist must show release-status -> physical-audio-handoff -> "
            "release-evidence -> release-evidence-score -> release in order"
        )

    for label, pattern in REQUIRED_PATTERNS.items():
        if not pattern.search(text):
            raise AssertionError(f"release checklist missing required guidance: {label}")
    for disallowed in DISALLOWED_TEXT:
        if disallowed in text:
            raise AssertionError(f"release checklist still contains stale command: {disallowed}")
    for path, disallowed_items in DISALLOWED_DOC_TEXT.items():
        doc_text = path.read_text(encoding="utf-8")
        for disallowed in disallowed_items:
            if disallowed in doc_text:
                raise AssertionError(f"{path.relative_to(ROOT)} still contains invalid placeholder label: {disallowed}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="accepted by the category runner; validation runs by default",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parse_args(argv or sys.argv[1:])
    validate()
    print("release checklist contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
