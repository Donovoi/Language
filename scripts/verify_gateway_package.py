#!/usr/bin/env python3
"""Verify that gateway package artifacts expose the packaged CLI."""

from __future__ import annotations

import argparse
from importlib.metadata import entry_points
import io
from pathlib import Path
import tarfile
import tempfile
import zipfile


EXPECTED_ENTRY_POINT = "app.cli:main"
EXPECTED_ENTRY_LINE = f"language-gateway = {EXPECTED_ENTRY_POINT}"
EXPECTED_PYPROJECT_ENTRY_LINE = 'language-gateway = "app.cli:main"'
REQUIRED_HELP_FLAGS = ("--host", "--port", "--log-level")


def verify_installed_entry_point() -> None:
    matches = [
        entry_point
        for entry_point in entry_points(group="console_scripts")
        if entry_point.name == "language-gateway"
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one language-gateway console script, found {len(matches)}")
    if matches[0].value != EXPECTED_ENTRY_POINT:
        raise AssertionError(f"unexpected language-gateway entry point: {matches[0].value!r}")

    from app.cli import build_parser

    help_text = build_parser().format_help()
    for flag in REQUIRED_HELP_FLAGS:
        if flag not in help_text:
            raise AssertionError(f"gateway CLI help missing {flag}")


def verify_wheel_entry_point(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()
        entry_files = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        if len(entry_files) != 1:
            raise AssertionError(f"expected one wheel entry_points.txt, found {len(entry_files)}")
        entry_text = archive.read(entry_files[0]).decode("utf-8")
        if EXPECTED_ENTRY_LINE not in entry_text:
            raise AssertionError(f"wheel does not expose {EXPECTED_ENTRY_LINE}")
        if "app/cli.py" not in names:
            raise AssertionError("wheel does not include app/cli.py")


def _read_sdist_member(archive: tarfile.TarFile, suffix: str) -> str:
    matches = [member for member in archive.getmembers() if member.name.endswith(suffix)]
    if len(matches) != 1:
        raise AssertionError(f"expected one sdist member ending {suffix!r}, found {len(matches)}")
    extracted = archive.extractfile(matches[0])
    if extracted is None:
        raise AssertionError(f"could not read sdist member {matches[0].name}")
    return extracted.read().decode("utf-8")


def verify_sdist_entry_point(sdist_path: Path) -> None:
    with tarfile.open(sdist_path, "r:gz") as archive:
        names = archive.getnames()
        if not any(name.endswith("/app/cli.py") for name in names):
            raise AssertionError("sdist does not include app/cli.py")
        pyproject = _read_sdist_member(archive, "/pyproject.toml")
        if EXPECTED_PYPROJECT_ENTRY_LINE not in pyproject:
            raise AssertionError(
                f"sdist pyproject.toml does not expose {EXPECTED_PYPROJECT_ENTRY_LINE}"
            )


def _write_text_tar_member(archive: tarfile.TarFile, name: str, text: str) -> None:
    payload = text.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        wheel = temp_dir / "language_gateway-0.1.0-py3-none-any.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("app/cli.py", "def main(): pass\n")
            archive.writestr(
                "language_gateway-0.1.0.dist-info/entry_points.txt",
                f"[console_scripts]\n{EXPECTED_ENTRY_LINE}\n",
            )
        verify_wheel_entry_point(wheel)

        sdist = temp_dir / "language_gateway-0.1.0.tar.gz"
        with tarfile.open(sdist, "w:gz") as archive:
            _write_text_tar_member(archive, "language_gateway-0.1.0/app/cli.py", "")
            _write_text_tar_member(
                archive,
                "language_gateway-0.1.0/pyproject.toml",
                f"[project.scripts]\n{EXPECTED_PYPROJECT_ENTRY_LINE}\n",
            )
        verify_sdist_entry_point(sdist)

        bad_wheel = temp_dir / "bad.whl"
        with zipfile.ZipFile(bad_wheel, "w") as archive:
            archive.writestr("app/cli.py", "")
        try:
            verify_wheel_entry_point(bad_wheel)
        except AssertionError:
            pass
        else:
            raise AssertionError("bad wheel should fail verification")

    print("gateway package verifier self-test PASS")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", action="store_true", help="verify installed console metadata")
    parser.add_argument("--wheel", type=Path, help="gateway wheel to inspect")
    parser.add_argument("--sdist", type=Path, help="gateway source distribution to inspect")
    parser.add_argument("--self-test", action="store_true", help="run verifier contract checks")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if not args.installed and args.wheel is None and args.sdist is None:
        raise SystemExit("provide --installed, --wheel, --sdist, or --self-test")
    if args.installed:
        verify_installed_entry_point()
        print("gateway installed entry point PASS")
    if args.wheel is not None:
        verify_wheel_entry_point(args.wheel)
        print("gateway wheel entry point PASS")
    if args.sdist is not None:
        verify_sdist_entry_point(args.sdist)
        print("gateway sdist entry point PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
