#!/usr/bin/env python3
"""Run curated Language test categories.

This script is intentionally explicit. The repo has many useful low-level
Makefile and PowerShell targets; this file groups them into user-facing suites
without hiding which commands will run.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEV_CONTAINER = "scripts/dev_container.ps1"


@dataclass(frozen=True)
class Step:
    name: str
    description: str
    local_args: tuple[str, ...] = ()
    target: str = ""
    target_args: tuple[str, ...] = ()
    make_env: dict[str, str] = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return bool(self.local_args)


@dataclass(frozen=True)
class Category:
    name: str
    description: str
    steps: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


STEPS: dict[str, Step] = {
    "release-audio-gate-self-test": Step(
        name="release-audio-gate-self-test",
        description="release gate parser/report contract self-test",
        local_args=("{python}", "scripts/release_audio_gate.py", "--self-test"),
    ),
    "release-audio-status-self-test": Step(
        name="release-audio-status-self-test",
        description="compact release status summary contract self-test",
        local_args=("{python}", "scripts/release_audio_status.py", "--self-test"),
    ),
    "gateway-package-verifier-self-test": Step(
        name="gateway-package-verifier-self-test",
        description="gateway package entry-point verifier contract self-test",
        local_args=("{python}", "scripts/verify_gateway_package.py", "--self-test"),
    ),
    "release-audio-status": Step(
        name="release-audio-status",
        description="compact release gate blocker, next-action summary, and physical-audio checklist",
        local_args=("{python}", "scripts/release_audio_status.py", "--write-operator-checklist"),
    ),
    "headphone-route-triage-handoff-self-test": Step(
        name="headphone-route-triage-handoff-self-test",
        description="headphone route-triage handoff contract self-test",
        local_args=("{python}", "scripts/headphone_route_triage_handoff.py", "--self-test"),
    ),
    "headphone-local-preflight": Step(
        name="headphone-local-preflight",
        description="host-local no-audio headphone route preflight",
        local_args=(
            "pwsh",
            "-NoProfile",
            "-File",
            "scripts/headphone_isolation_local.ps1",
            "-Action",
            "preflight",
            "--sample-rate-hz",
            "48000",
            "--input-channels",
            "1",
            "--output-channels",
            "2",
        ),
    ),
    "headphone-route-triage-handoff": Step(
        name="headphone-route-triage-handoff",
        description="print the deliberate non-release route-probe command from preflight",
        local_args=("{python}", "scripts/headphone_route_triage_handoff.py"),
    ),
    "live-microphone-capture-contract": Step(
        name="live-microphone-capture-contract",
        description="live microphone artifact/scorer contract self-test",
        local_args=("{python}", "scripts/run_live_microphone_capture.py", "self-test"),
    ),
    "headphone-isolation-contract": Step(
        name="headphone-isolation-contract",
        description="headphone/earpiece isolation scorer contract self-test",
        local_args=("{python}", "scripts/run_headphone_isolation_check.py", "self-test"),
    ),
    "real-room-playback-contract": Step(
        name="real-room-playback-contract",
        description="real-room playback/suppression scorer contract self-test",
        local_args=("{python}", "scripts/run_real_room_playback_suppression.py", "self-test"),
    ),
    "fixture-live-capture-contract": Step(
        name="fixture-live-capture-contract",
        description="fixture live-capture benchmark contract self-test",
        local_args=("{python}", "scripts/benchmark_live_capture_fixture.py", "--self-test"),
    ),
    "fixture-playback-suppression-contract": Step(
        name="fixture-playback-suppression-contract",
        description="fixture playback/suppression benchmark contract self-test",
        local_args=("{python}", "scripts/benchmark_playback_suppression_fixture.py", "--self-test"),
    ),
    "fallback-tts-contract": Step(
        name="fallback-tts-contract",
        description="fallback TTS report contract self-test",
        local_args=("{python}", "scripts/benchmark_fallback_tts_fixture.py", "--self-test"),
    ),
    "same-voice-candidate-contract": Step(
        name="same-voice-candidate-contract",
        description="same-voice candidate validator contract self-test",
        local_args=("{python}", "scripts/benchmark_same_voice_candidate_fixture.py", "--self-test"),
    ),
    "speechbrain-voice-similarity-contract": Step(
        name="speechbrain-voice-similarity-contract",
        description="SpeechBrain voice-similarity report contract self-test",
        local_args=("{python}", "scripts/run_speechbrain_voice_similarity_fixture.py", "--self-test"),
    ),
    "core-check": Step(
        name="core-check",
        description="repo contract, Rust, gateway, and Flutter/core checks",
        target="check",
    ),
    "audio-eval-build": Step(
        name="audio-eval-build",
        description="build the disposable audio-eval Docker image",
        target="audio-eval-build",
    ),
    "audio-eval-check": Step(
        name="audio-eval-check",
        description="deterministic audio-eval harness",
        target="audio-eval-check",
    ),
    "audio-eval-real-speech-check": Step(
        name="audio-eval-real-speech-check",
        description="tiny real-speech overlap fixture",
        target="audio-eval-real-speech-check",
    ),
    "audio-eval-real-speech-chunked-check": Step(
        name="audio-eval-real-speech-chunked-check",
        description="chunked real-speech overlap fixture",
        target="audio-eval-real-speech-chunked-check",
    ),
    "audio-eval-crowd-noise-check": Step(
        name="audio-eval-crowd-noise-check",
        description="crowd-noise catalog/fixture check",
        target="audio-eval-crowd-noise-check",
    ),
    "audio-eval-translation-check": Step(
        name="audio-eval-translation-check",
        description="multilingual language-ID and translation fixture",
        target="audio-eval-translation-check",
    ),
    "audio-eval-live-capture-check": Step(
        name="audio-eval-live-capture-check",
        description="fixture replay of timestamped capture chunks",
        target="audio-eval-live-capture-check",
    ),
    "audio-eval-playback-suppression-check": Step(
        name="audio-eval-playback-suppression-check",
        description="synthetic translated-playback/suppression fixture",
        target="audio-eval-playback-suppression-check",
    ),
    "audio-eval-fallback-tts-check": Step(
        name="audio-eval-fallback-tts-check",
        description="neutral fallback TTS fixture evidence",
        target="audio-eval-fallback-tts-check",
    ),
    "same-voice-candidate-check": Step(
        name="same-voice-candidate-check",
        description="score generated same-voice candidate artifacts",
        target="audio-eval-same-voice-candidate-check",
        target_args=(
            "--manifest",
            "artifacts/audio_eval/runs/same-voice-candidate/same-voice-candidate-manifest.json",
        ),
        make_env={
            "SAME_VOICE_CANDIDATE_ARGS": (
                "--manifest "
                "artifacts/audio_eval/runs/same-voice-candidate/same-voice-candidate-manifest.json"
            )
        },
    ),
    "speechbrain-voice-similarity-check": Step(
        name="speechbrain-voice-similarity-check",
        description="score same-voice candidate report with SpeechBrain ECAPA",
        target="audio-eval-speechbrain-voice-similarity-check",
        target_args=(
            "--candidate-report",
            "artifacts/audio_eval/runs/same-voice-candidate/voice-clone-report.json",
            "--score-warning-only",
        ),
        make_env={
            "SPEECHBRAIN_VOICE_SIMILARITY_ARGS": (
                "--candidate-report "
                "artifacts/audio_eval/runs/same-voice-candidate/voice-clone-report.json "
                "--score-warning-only"
            )
        },
    ),
    "audio-eval-pyannote-check": Step(
        name="audio-eval-pyannote-check",
        description="optional pyannote diarization baseline",
        target="audio-eval-pyannote-check",
    ),
    "audio-eval-sortformer-rolling-check": Step(
        name="audio-eval-sortformer-rolling-check",
        description="optional Sortformer rolling real-speech baseline",
        target="audio-eval-sortformer-rolling-real-speech-check",
    ),
    "audio-eval-whisper-rolling-check": Step(
        name="audio-eval-whisper-rolling-check",
        description="optional rolling Whisper translation baseline",
        target="audio-eval-whisper-rolling-translation-check",
    ),
    "audio-eval-wesep-check": Step(
        name="audio-eval-wesep-check",
        description="optional WeSep enrolled target-speaker extraction baseline",
        target="audio-eval-wesep-check",
    ),
    "audio-eval-whisper-wesep-causal-check": Step(
        name="audio-eval-whisper-wesep-causal-check",
        description="optional causal Sortformer + WeSep + Whisper bridge",
        target="audio-eval-whisper-wesep-causal-translation-check",
    ),
    "live-microphone-list-devices": Step(
        name="live-microphone-list-devices",
        description="list host microphone devices",
        target="live-microphone-capture-list-devices",
    ),
    "headphone-isolation-list-devices": Step(
        name="headphone-isolation-list-devices",
        description="list host audio devices for listener-ear routing",
        target="headphone-isolation-list-devices",
    ),
    "headphone-isolation-preflight": Step(
        name="headphone-isolation-preflight",
        description="classify host audio routes without playing or recording audio",
        target="headphone-isolation-preflight",
        target_args=("--sample-rate-hz", "48000", "--input-channels", "1", "--output-channels", "2"),
        make_env={
            "HEADPHONE_ISOLATION_PREFLIGHT_ARGS": (
                "--sample-rate-hz 48000 --input-channels 1 --output-channels 2"
            )
        },
    ),
    "headphone-isolation-virtual-lab": Step(
        name="headphone-isolation-virtual-lab",
        description="development-only virtual listener-ear lab",
        target="headphone-isolation-virtual-lab",
    ),
    "headphone-isolation-collect-evidence": Step(
        name="headphone-isolation-collect-evidence",
        description="prepare/check the manual listener-ear evidence kit and raw WAV dropbox",
        target="headphone-isolation-collect-evidence",
        target_args=("--sample-rate-hz", "48000", "--playback-gain-db", "-18"),
        make_env={
            "HEADPHONE_ISOLATION_COLLECT_EVIDENCE_ARGS": (
                "--sample-rate-hz 48000 --playback-gain-db -18"
            )
        },
    ),
    "headphone-isolation-check-manual": Step(
        name="headphone-isolation-check-manual",
        description="check whether manual listener-ear WAVs are ready to score",
        target="headphone-isolation-check-manual",
        target_args=("--score-warning-only",),
        make_env={"HEADPHONE_ISOLATION_CHECK_MANUAL_ARGS": "--score-warning-only"},
    ),
    "release-audio-gate": Step(
        name="release-audio-gate",
        description="strict release gate; fails until required evidence is present",
        target="release-audio-gate",
    ),
}


CATEGORIES: dict[str, Category] = {
    "quick": Category(
        name="quick",
        description="Fast local sanity checks; no Docker, no model download, no hardware access.",
        steps=(
            "release-audio-gate-self-test",
            "release-audio-status-self-test",
            "gateway-package-verifier-self-test",
            "headphone-route-triage-handoff-self-test",
            "live-microphone-capture-contract",
            "headphone-isolation-contract",
            "real-room-playback-contract",
        ),
    ),
    "contracts": Category(
        name="contracts",
        description="All local audio/report contract self-tests; no Docker or physical hardware.",
        steps=(
            "release-audio-gate-self-test",
            "release-audio-status-self-test",
            "gateway-package-verifier-self-test",
            "headphone-route-triage-handoff-self-test",
            "live-microphone-capture-contract",
            "headphone-isolation-contract",
            "real-room-playback-contract",
            "fixture-live-capture-contract",
            "fixture-playback-suppression-contract",
            "fallback-tts-contract",
            "same-voice-candidate-contract",
            "speechbrain-voice-similarity-contract",
        ),
    ),
    "core": Category(
        name="core",
        description="Repo contract, Rust, gateway, and app/core validation.",
        steps=("core-check",),
        notes=(
            "With --runner make this uses make check.",
            "With --runner powershell this uses scripts/dev_container.ps1 check.",
        ),
    ),
    "audio-fixtures": Category(
        name="audio-fixtures",
        description="Disposable Docker audio fixtures for capture, translation, playback, and fallback TTS.",
        steps=(
            "audio-eval-build",
            "audio-eval-check",
            "audio-eval-real-speech-check",
            "audio-eval-real-speech-chunked-check",
            "audio-eval-crowd-noise-check",
            "audio-eval-translation-check",
            "audio-eval-live-capture-check",
            "audio-eval-playback-suppression-check",
            "audio-eval-fallback-tts-check",
        ),
        notes=("May download small public datasets the first time it runs.",),
    ),
    "voice-candidates": Category(
        name="voice-candidates",
        description="Validate generated same-voice candidate artifacts and optional ASV scoring.",
        steps=(
            "same-voice-candidate-contract",
            "same-voice-candidate-check",
            "speechbrain-voice-similarity-contract",
            "speechbrain-voice-similarity-check",
        ),
        notes=(
            "The candidate checks need generated artifacts under artifacts/audio_eval/runs/same-voice-candidate/.",
            "Use contracts when you only want a no-artifact self-test.",
        ),
    ),
    "optional-models": Category(
        name="optional-models",
        description="Heavier model-backed baselines for diarization, TSE, and translation.",
        steps=(
            "audio-eval-pyannote-check",
            "audio-eval-sortformer-rolling-check",
            "audio-eval-whisper-rolling-check",
            "audio-eval-wesep-check",
            "audio-eval-whisper-wesep-causal-check",
        ),
        notes=(
            "Some steps need HF_TOKEN and accepted model terms.",
            "Expect model downloads and longer runtime.",
        ),
    ),
    "hardware": Category(
        name="hardware",
        description="Host-audio discovery and non-release listener-ear planning.",
        steps=(
            "live-microphone-list-devices",
            "headphone-isolation-list-devices",
            "headphone-isolation-preflight",
            "headphone-isolation-virtual-lab",
        ),
        notes=(
            "Preflight does not play or record audio.",
            "Physical release evidence still requires real listener-ear WAVs.",
        ),
    ),
    "route-triage": Category(
        name="route-triage",
        description="Refresh host headphone preflight and print a deliberate non-release route probe.",
        steps=(
            "headphone-local-preflight",
            "headphone-route-triage-handoff",
        ),
        notes=(
            "Does not run the printed probe command automatically.",
            "The printed command plays/records a short probe and remains release_proof=false.",
        ),
    ),
    "evidence-kit": Category(
        name="evidence-kit",
        description="Prepare/check the manual listener-ear recording kit and raw WAV dropbox.",
        steps=("headphone-isolation-collect-evidence",),
        notes=(
            "Does not play audio or record by itself.",
            "After exporting the three listener-ear WAVs into the dropbox, rerun this category.",
        ),
    ),
    "recording-status": Category(
        name="recording-status",
        description="Check whether the three listener-ear WAVs are ready to score.",
        steps=("headphone-isolation-check-manual",),
        notes=(
            "Use after placing the open-ear source, isolated source, and translated playback WAVs in the dropbox.",
        ),
    ),
    "release-evidence": Category(
        name="release-evidence",
        description="One-command listener-ear evidence handoff: prepare/import/check, then print release status.",
        steps=(
            "headphone-isolation-collect-evidence",
            "headphone-isolation-check-manual",
            "release-audio-status",
        ),
        notes=(
            "Does not record audio or score with placeholder labels.",
            "Use after placing recorder exports in the raw WAV dropbox, or before capture to create the kit.",
        ),
    ),
    "release": Category(
        name="release",
        description="Strict release gate status. A nonzero exit means release evidence is still missing or failing.",
        steps=("release-audio-gate",),
    ),
    "release-status": Category(
        name="release-status",
        description="Compact release status and next-action handoff. Exits zero unless the wrapper fails.",
        steps=("release-audio-status",),
        notes=(
            "Use release for the strict nonzero release gate.",
            "Use release-status in low-token agent handoffs.",
        ),
    ),
    "all": Category(
        name="all",
        description="All automated non-interactive suites: quick, core, and Docker audio fixtures.",
        includes=("quick", "core", "audio-fixtures"),
        notes=(
            "Excludes hardware, release, optional-models, and artifact-dependent voice-candidates.",
            "Run those categories explicitly when you have devices, tokens, or candidate artifacts ready.",
        ),
    ),
}


def available_make_targets() -> set[str]:
    makefile = ROOT / "Makefile"
    if not makefile.exists():
        return set()
    targets: set[str] = set()
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("\t") or line.startswith("."):
            continue
        if ":" not in line:
            continue
        target = line.split(":", 1)[0].strip()
        if target and " " not in target and "\t" not in target:
            targets.add(target)
    return targets


def resolve_category_steps(category_name: str, seen: tuple[str, ...] = ()) -> list[Step]:
    if category_name not in CATEGORIES:
        raise KeyError(f"unknown category: {category_name}")
    if category_name in seen:
        chain = " -> ".join((*seen, category_name))
        raise ValueError(f"category include cycle: {chain}")
    category = CATEGORIES[category_name]
    steps: list[Step] = []
    for included in category.includes:
        steps.extend(resolve_category_steps(included, (*seen, category_name)))
    for step_name in category.steps:
        steps.append(STEPS[step_name])
    return steps


def choose_runner(runner: str) -> str:
    if runner != "auto":
        return runner
    if platform.system().lower().startswith("win"):
        return "powershell"
    return "make"


def expand_local_args(args: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    for arg in args:
        if arg == "{python}":
            expanded.append(sys.executable)
        else:
            expanded.append(arg)
    return expanded


def command_for_step(step: Step, runner: str) -> tuple[list[str], dict[str, str]]:
    if step.is_local:
        return expand_local_args(step.local_args), {}
    if not step.target:
        raise ValueError(f"step {step.name} has no local_args or target")
    if runner == "make":
        return ["make", step.target], dict(step.make_env)
    if runner == "powershell":
        return ["pwsh", "-NoProfile", "-File", DEV_CONTAINER, step.target, *step.target_args], {}
    raise ValueError(f"unsupported runner for target step {step.name}: {runner}")


def format_command(command: Iterable[str], env_delta: dict[str, str]) -> str:
    env_prefix = " ".join(f"{key}={value!r}" for key, value in sorted(env_delta.items()))
    rendered = " ".join(command)
    return f"{env_prefix} {rendered}".strip()


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "step"


def tail_lines(path: Path, limit: int) -> list[str]:
    if limit <= 0 or not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-limit:]


def list_categories() -> int:
    print("Available test categories:\n")
    for name in sorted(CATEGORIES):
        category = CATEGORIES[name]
        steps = resolve_category_steps(name)
        print(f"{name:18} {len(steps):2d} step(s)  {category.description}")
        for note in category.notes:
            print(f"{'':22}- {note}")
    return 0


def run_category(args: argparse.Namespace) -> int:
    runner = choose_runner(args.runner)
    steps = resolve_category_steps(args.category)
    log_dir = Path(args.log_dir)
    if not log_dir.is_absolute():
        log_dir = ROOT / log_dir
    if args.quiet and not args.dry_run:
        log_dir = log_dir / safe_filename(args.category)
        log_dir.mkdir(parents=True, exist_ok=True)
    elif args.quiet:
        log_dir = log_dir / safe_filename(args.category)
    print(f"Category: {args.category}")
    print(f"Runner: {runner}")
    print(f"Steps: {len(steps)}")
    if args.quiet:
        print(f"Output: quiet; full logs under {repo_relative(log_dir)}")
    if args.dry_run:
        print("")
        for index, step in enumerate(steps, start=1):
            command, env_delta = command_for_step(step, runner)
            print(f"{index}. {step.name}: {step.description}")
            print(f"   {format_command(command, env_delta)}")
            if args.quiet:
                log_path = log_dir / f"{index:02d}-{safe_filename(step.name)}.log"
                print(f"   log: {repo_relative(log_path)}")
        return 0

    failures: list[tuple[str, int]] = []
    for index, step in enumerate(steps, start=1):
        command, env_delta = command_for_step(step, runner)
        env = os.environ.copy()
        env.update(env_delta)
        print("")
        print(f"==> [{index}/{len(steps)}] {step.name}")
        print(format_command(command, env_delta))
        if args.quiet:
            log_path = log_dir / f"{index:02d}-{safe_filename(step.name)}.log"
            with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
                log_file.write(f"$ {format_command(command, env_delta)}\n\n")
                log_file.flush()
                result = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            print(f"log: {repo_relative(log_path)}")
        else:
            result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        if result.returncode != 0:
            failures.append((step.name, result.returncode))
            if args.quiet:
                print(f"{step.name} failed with exit code {result.returncode}; last log lines:")
                for line in tail_lines(log_path, args.tail_lines):
                    print(line)
            if not args.continue_on_failure:
                if not args.quiet:
                    print(f"{step.name} failed with exit code {result.returncode}.")
                return result.returncode

    if failures:
        print("")
        print("Category completed with failures:")
        for name, returncode in failures:
            print(f"- {name}: exit code {returncode}")
        return 1

    print("")
    print(f"Category {args.category} passed.")
    return 0


def self_test() -> int:
    make_targets = available_make_targets()
    missing_targets = sorted(
        step.target for step in STEPS.values() if step.target and step.target not in make_targets
    )
    if missing_targets:
        raise AssertionError(f"category target missing from Makefile: {missing_targets}")
    missing_steps = sorted(
        step_name
        for category in CATEGORIES.values()
        for step_name in category.steps
        if step_name not in STEPS
    )
    if missing_steps:
        raise AssertionError(f"category references unknown steps: {missing_steps}")
    for category_name in CATEGORIES:
        steps = resolve_category_steps(category_name)
        if not steps:
            raise AssertionError(f"category has no steps: {category_name}")
        for runner in ("make", "powershell"):
            for step in steps:
                command_for_step(step, runner)
    for excluded in ("hardware", "release", "optional-models", "voice-candidates"):
        if excluded in CATEGORIES["all"].includes:
            raise AssertionError(f"all should not implicitly include {excluded}")
    if not shutil.which("pwsh"):
        print("warning: pwsh not found; dry-run still validates command construction")
    print("test category self-test PASS")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run curated Language test categories")
    parser.add_argument(
        "category",
        nargs="?",
        default="quick",
        choices=(*sorted(CATEGORIES), "list"),
        help="category to run, or 'list' to show categories",
    )
    parser.add_argument(
        "--runner",
        choices=("auto", "make", "powershell"),
        default="auto",
        help="how target-based steps are invoked; local self-tests always use this Python",
    )
    parser.add_argument("--dry-run", action="store_true", help="print commands without running them")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--quiet",
        dest="quiet",
        action="store_true",
        default=True,
        help="write step output to artifacts/test-categories and print only summaries/tails (default)",
    )
    output_group.add_argument(
        "--verbose",
        dest="quiet",
        action="store_false",
        help="stream full step output to the terminal",
    )
    parser.add_argument(
        "--log-dir",
        default="artifacts/test-categories",
        help="directory for --quiet step logs",
    )
    parser.add_argument(
        "--tail-lines",
        type=int,
        default=40,
        help="number of log lines to print for a failing quiet step",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="run remaining steps after a failure and summarize at the end",
    )
    parser.add_argument("--self-test", action="store_true", help="validate category definitions")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        return self_test()
    if args.category == "list":
        return list_categories()
    return run_category(args)


if __name__ == "__main__":
    raise SystemExit(main())
