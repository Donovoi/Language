#!/usr/bin/env python3
"""Run audio fixture contract checks in a managed local virtualenv."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VENV = ROOT / ".venv-audio-contract"
DEFAULT_REQUIREMENTS = ROOT / "docker" / "dev" / "requirements-audio-eval.txt"
MARKER_NAME = ".language-audio-contract-env.json"


def _run(command: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, check=False)


def _capture(command: list[str]) -> str | None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pinned_requirements(requirements: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in requirements.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)$", line)
        if not match:
            raise SystemExit(f"Audio contract requirements must be exact pins: {raw_line!r}")
        pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    if not pins:
        raise SystemExit(f"Audio contract requirements file has no package pins: {requirements}")
    return pins


def _python_version(candidate: str) -> tuple[int, int, int] | None:
    output = _capture(
        [
            candidate,
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
        ]
    )
    if output is None:
        return None
    parts = output.split(".", 2)
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def _is_supported_python(candidate: str) -> bool:
    version = _python_version(candidate)
    return version is not None and version[0] == 3 and 11 <= version[1] < 14


def _resolve_executable(candidate: str) -> str | None:
    if not candidate:
        return None
    path = Path(candidate)
    if path.exists():
        return str(path.resolve())
    return shutil.which(candidate)


def resolve_supported_python(requested: str) -> str:
    candidates: list[str] = []
    if requested:
        candidates.append(requested)
    for name in (
        "LANGUAGE_AUDIO_CONTRACT_PYTHON",
        "LANGUAGE_PACKAGE_PYTHON",
        "LANGUAGE_PYTHON",
        "PYTHON",
    ):
        value = os.environ.get(name, "").strip()
        if value:
            candidates.append(value)
    codex_python = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "python"
        / "python.exe"
    )
    if codex_python.exists():
        candidates.append(str(codex_python))
    candidates.extend([sys.executable, "python3", "python"])

    seen: set[str] = set()
    errors: list[str] = []
    for raw_candidate in candidates:
        resolved = _resolve_executable(raw_candidate)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        if _is_supported_python(resolved):
            return resolved
        version = _python_version(resolved)
        errors.append(f"{raw_candidate} -> {resolved} ({version or 'unusable'})")

    detail = "; ".join(errors)
    raise SystemExit(
        "Could not find Python >=3.11,<3.14 for audio contract checks. "
        "Set LANGUAGE_AUDIO_CONTRACT_PYTHON or pass --python. "
        f"Candidates: {detail}"
    )


def venv_python(venv: Path) -> Path:
    windows = venv / "Scripts" / "python.exe"
    if windows.exists():
        return windows
    posix = venv / "bin" / "python"
    if posix.exists():
        return posix
    return windows


def marker_payload(base_python: str, requirements: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "base_python": str(Path(base_python).resolve()),
        "base_python_version": ".".join(str(part) for part in (_python_version(base_python) or ())),
        "requirements": str(requirements.resolve().relative_to(ROOT)),
        "requirements_sha256": _sha256(requirements),
    }


def installed_versions_match(python: Path, requirements: Path) -> bool:
    pins = parse_pinned_requirements(requirements)
    script = "\n".join(
        [
            "import importlib.metadata as metadata",
            "import json",
            "import sys",
            "pins = json.loads(sys.argv[1])",
            "errors = []",
            "for name, expected in pins.items():",
            "    try:",
            "        actual = metadata.version(name)",
            "    except metadata.PackageNotFoundError:",
            "        errors.append(f'{name} missing')",
            "        continue",
            "    if actual != expected:",
            "        errors.append(f'{name}=={actual} expected {expected}')",
            "if errors:",
            "    print('; '.join(errors))",
            "    raise SystemExit(1)",
        ]
    )
    result = _run([str(python), "-c", script, json.dumps(pins, sort_keys=True)])
    return result.returncode == 0


def marker_matches(venv: Path, expected: dict[str, object], requirements: Path) -> bool:
    marker = venv / MARKER_NAME
    python = venv_python(venv)
    if not marker.exists() or not python.exists():
        return False
    try:
        actual = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if actual != expected:
        return False
    result = _run(
        [
            str(python),
            "-c",
            "import numpy, scipy, soundfile; print('audio contract deps ok')",
        ]
    )
    return result.returncode == 0 and installed_versions_match(python, requirements)


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def ensure_audio_contract_env(base_python: str, venv: Path, requirements: Path) -> Path:
    if not requirements.exists():
        raise SystemExit(f"Audio contract requirements file not found: {requirements}")
    if not _inside_repo(venv):
        raise SystemExit(f"Refusing to manage audio contract venv outside the repo: {venv}")
    if venv.exists() and not (venv / "pyvenv.cfg").exists():
        raise SystemExit(
            f"Refusing to reuse {venv} because it is not a Python virtualenv with pyvenv.cfg."
        )
    is_default_venv = venv.resolve() == DEFAULT_VENV.resolve()
    marker = venv / MARKER_NAME
    if venv.exists() and not is_default_venv and not marker.exists():
        raise SystemExit(
            f"Refusing to clear custom venv {venv} without {MARKER_NAME}. "
            f"Use the default {DEFAULT_VENV.relative_to(ROOT)} path or choose an empty custom path."
        )

    expected_marker = marker_payload(base_python, requirements)
    if marker_matches(venv, expected_marker, requirements):
        return venv_python(venv)

    venv.parent.mkdir(parents=True, exist_ok=True)
    result = _run([base_python, "-m", "venv", "--clear", str(venv)])
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    python = venv_python(venv)
    if not python.exists():
        raise SystemExit(f"Audio contract venv Python was not created under {venv}")

    for command in (
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        [str(python), "-m", "pip", "install", "-r", str(requirements)],
    ):
        result = _run(command)
        if result.returncode != 0:
            raise SystemExit(result.returncode)

    (venv / MARKER_NAME).write_text(
        json.dumps(expected_marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return python


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default="", help="base Python >=3.11,<3.14 for the venv")
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--self-test", action="store_true", help="validate runner helpers")
    parser.add_argument("script", nargs="?")
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        if not _inside_repo(DEFAULT_VENV):
            raise AssertionError("default venv should be repo-local")
        if not DEFAULT_REQUIREMENTS.exists():
            raise AssertionError("default audio requirements file is missing")
        if not parse_pinned_requirements(DEFAULT_REQUIREMENTS):
            raise AssertionError("default audio requirements file should include exact pins")
        resolve_supported_python(args.python)
        print("audio contract runner self-test PASS")
        return 0

    if not args.script:
        raise SystemExit("provide a script to run")

    script = resolve_repo_path(Path(args.script))
    if not script.exists():
        raise SystemExit(f"script not found: {script}")

    venv = resolve_repo_path(args.venv)
    requirements = resolve_repo_path(args.requirements)
    base_python = resolve_supported_python(args.python)
    audio_python = ensure_audio_contract_env(base_python, venv, requirements)
    command = [str(audio_python), str(script), *args.script_args]
    return _run(command).returncode


if __name__ == "__main__":
    raise SystemExit(main())
