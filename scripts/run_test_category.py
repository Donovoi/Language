#!/usr/bin/env python3
"""Run curated Language test categories.

This script is intentionally explicit. The repo has many useful low-level
Makefile and PowerShell targets; this file groups them into user-facing suites
without hiding which commands will run.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEV_CONTAINER = "scripts/dev_container.ps1"
ENV_ARG_PATTERN = re.compile(r"^\{env:([A-Za-z_][A-Za-z0-9_]*)(?::([^{}]*))?\}$")
PORTABLE_FLUTTER = Path("C:/tmp/flutter/bin/flutter.bat")
MANUAL_RECORDING_FILENAMES = {
    "source_open_ear_recording": "source-open-ear-recording.wav",
    "source_isolated_ear_recording": "source-isolated-ear-recording.wav",
    "translated_headphone_recording": "translated-headphone-recording.wav",
}
MANUAL_RECORDING_DROPBOX = (
    "artifacts/audio_eval/runs/headphone-earpiece-manual-kit/raw-listener-ear-recordings"
)
PLACEHOLDER_REQUIRED_ENV_VALUES = {
    "HEADPHONE_OUTPUT",
    "LANGUAGE_HEADPHONE_OUTPUT_DEVICE",
    "LANGUAGE_HEADPHONE_DEVICE_LABEL",
    "LANGUAGE_ISOLATION_FIXTURE_LABEL",
    "LANGUAGE_MEASUREMENT_MICROPHONE_LABEL",
    "LANGUAGE_MEASUREMENT_INPUT_DEVICE",
    "LANGUAGE_SOURCE_OUTPUT_DEVICE",
    "LISTENER_EAR_INPUT",
    "REPLACE_WITH_EARCUP_AND_MIC_POSITION",
    "REPLACE_WITH_HEADPHONE_MODEL",
    "REPLACE_WITH_MIC_MODEL_AND_POSITION",
    "SOURCE_SPEAKER_OUTPUT",
}


@dataclass(frozen=True)
class Step:
    name: str
    description: str
    local_args: tuple[str, ...] = ()
    powershell_args: tuple[str, ...] = ()
    target: str = ""
    target_args: tuple[str, ...] = ()
    make_env: dict[str, str] = field(default_factory=dict)
    required_env: tuple[str, ...] = ()

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
    success_hints: tuple[str, ...] = ()
    handoff_log_steps: tuple[str, ...] = ()
    manual_status_report: str = ""


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
    "release-progress-self-test": Step(
        name="release-progress-self-test",
        description="release progress estimate contract self-test",
        local_args=("{python}", "scripts/release_progress.py", "--self-test"),
    ),
    "release-checklist-contract": Step(
        name="release-checklist-contract",
        description="release checklist category-command contract",
        local_args=("{python}", "scripts/check_release_checklist.py", "--self-test"),
    ),
    "gateway-package-verifier-self-test": Step(
        name="gateway-package-verifier-self-test",
        description="gateway package entry-point verifier contract self-test",
        local_args=("{python}", "scripts/verify_gateway_package.py", "--self-test"),
    ),
    "gateway-auth-smoke-self-test": Step(
        name="gateway-auth-smoke-self-test",
        description="gateway auth smoke harness contract self-test",
        local_args=("{python}", "scripts/smoke_gateway_auth.py", "--self-test"),
    ),
    "audio-contract-runner-self-test": Step(
        name="audio-contract-runner-self-test",
        description="managed audio contract virtualenv runner self-test",
        local_args=("{python}", "scripts/run_audio_contract.py", "--self-test"),
    ),
    "release-audio-status": Step(
        name="release-audio-status",
        description="compact release gate blocker, next-action summary, and physical-audio checklist",
        local_args=("{python}", "scripts/release_audio_status.py", "--write-operator-checklist"),
    ),
    "release-progress": Step(
        name="release-progress",
        description="evidence-linked milestone completion estimate",
        local_args=("{python}", "scripts/release_progress.py"),
    ),
    "local-release-artifacts": Step(
        name="local-release-artifacts",
        description="build local source bundle and gateway package handoff",
        local_args=("pwsh", "-NoProfile", "-File", "scripts/package_local.ps1"),
    ),
    "gateway-package-smoke": Step(
        name="gateway-package-smoke",
        description="install the built gateway wheel and smoke the packaged CLI server",
        local_args=("pwsh", "-NoProfile", "-File", "scripts/smoke_gateway_package.ps1"),
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
        local_args=(
            "{python}",
            "scripts/run_audio_contract.py",
            "scripts/benchmark_live_capture_fixture.py",
            "--self-test",
        ),
    ),
    "fixture-playback-suppression-contract": Step(
        name="fixture-playback-suppression-contract",
        description="fixture playback/suppression benchmark contract self-test",
        local_args=(
            "{python}",
            "scripts/run_audio_contract.py",
            "scripts/benchmark_playback_suppression_fixture.py",
            "--self-test",
        ),
    ),
    "fallback-tts-contract": Step(
        name="fallback-tts-contract",
        description="fallback TTS report contract self-test",
        local_args=(
            "{python}",
            "scripts/run_audio_contract.py",
            "scripts/benchmark_fallback_tts_fixture.py",
            "--self-test",
        ),
    ),
    "same-voice-candidate-contract": Step(
        name="same-voice-candidate-contract",
        description="same-voice candidate validator contract self-test",
        local_args=(
            "{python}",
            "scripts/run_audio_contract.py",
            "scripts/benchmark_same_voice_candidate_fixture.py",
            "--self-test",
        ),
    ),
    "speechbrain-voice-similarity-contract": Step(
        name="speechbrain-voice-similarity-contract",
        description="SpeechBrain voice-similarity report contract self-test",
        local_args=(
            "{python}",
            "scripts/run_audio_contract.py",
            "scripts/run_speechbrain_voice_similarity_fixture.py",
            "--self-test",
        ),
    ),
    "core-check": Step(
        name="core-check",
        description="repo contract, Rust, gateway, and Flutter/core checks",
        powershell_args=(
            "pwsh",
            "-NoProfile",
            "-File",
            "scripts/check_local.ps1",
            "-UseExistingGatewayVenv",
            "-Python",
            "{env:LANGUAGE_CORE_PYTHON:services\\gateway\\.venv\\Scripts\\python.exe}",
            "-Flutter",
            "{flutter}",
        ),
        target="check",
    ),
    "smoke-local-demo": Step(
        name="smoke-local-demo",
        description="local gateway demo smoke for health/session/SSE",
        local_args=("pwsh", "-NoProfile", "-File", "scripts/smoke_local_demo.ps1"),
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
    "headphone-isolation-collect-and-score-evidence": Step(
        name="headphone-isolation-collect-and-score-evidence",
        description="import/check and score manual listener-ear evidence when WAVs and labels are ready",
        local_args=(
            "pwsh",
            "-NoProfile",
            "-File",
            DEV_CONTAINER,
            "headphone-isolation-collect-evidence",
            "--sample-rate-hz",
            "48000",
            "--playback-gain-db",
            "-18",
            "--allow-downmix",
            "--score-if-ready",
            "--headphone-device-label",
            "{env:LANGUAGE_HEADPHONE_DEVICE_LABEL:LANGUAGE_HEADPHONE_DEVICE_LABEL}",
            "--isolation-fixture-label",
            "{env:LANGUAGE_ISOLATION_FIXTURE_LABEL:LANGUAGE_ISOLATION_FIXTURE_LABEL}",
            "--measurement-microphone-label",
            "{env:LANGUAGE_MEASUREMENT_MICROPHONE_LABEL:LANGUAGE_MEASUREMENT_MICROPHONE_LABEL}",
        ),
        required_env=(
            "LANGUAGE_HEADPHONE_DEVICE_LABEL",
            "LANGUAGE_ISOLATION_FIXTURE_LABEL",
            "LANGUAGE_MEASUREMENT_MICROPHONE_LABEL",
        ),
    ),
    "headphone-isolation-check-manual": Step(
        name="headphone-isolation-check-manual",
        description="check whether manual listener-ear WAVs are ready to score",
        target="headphone-isolation-check-manual",
        target_args=("--score-warning-only",),
        make_env={"HEADPHONE_ISOLATION_CHECK_MANUAL_ARGS": "--score-warning-only"},
    ),
    "headphone-isolation-playback-plan": Step(
        name="headphone-isolation-playback-plan",
        description="dry-run the three-take manual reference playback plan without playing audio",
        local_args=(
            "pwsh",
            "-NoProfile",
            "-File",
            DEV_CONTAINER,
            "headphone-isolation-play-manual",
            "--manifest",
            "{env:LANGUAGE_MANUAL_RECORDING_MANIFEST:artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-manifest.json}",
            "--dry-run",
            "--source-output-device",
            "{env:LANGUAGE_SOURCE_OUTPUT_DEVICE:LANGUAGE_SOURCE_OUTPUT_DEVICE}",
            "--headphone-output-device",
            "{env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE:LANGUAGE_HEADPHONE_OUTPUT_DEVICE}",
        ),
        required_env=("LANGUAGE_SOURCE_OUTPUT_DEVICE", "LANGUAGE_HEADPHONE_OUTPUT_DEVICE"),
    ),
    "headphone-isolation-playback-session": Step(
        name="headphone-isolation-playback-session",
        description="play the three manual reference takes through explicit source/headphone outputs",
        local_args=(
            "pwsh",
            "-NoProfile",
            "-File",
            DEV_CONTAINER,
            "headphone-isolation-play-manual",
            "--manifest",
            "{env:LANGUAGE_MANUAL_RECORDING_MANIFEST:artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-manifest.json}",
            "--source-output-device",
            "{env:LANGUAGE_SOURCE_OUTPUT_DEVICE:LANGUAGE_SOURCE_OUTPUT_DEVICE}",
            "--headphone-output-device",
            "{env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE:LANGUAGE_HEADPHONE_OUTPUT_DEVICE}",
            "--countdown-s",
            "{env:LANGUAGE_MANUAL_PLAYBACK_COUNTDOWN_S:5}",
            "--non-interactive",
        ),
        required_env=("LANGUAGE_SOURCE_OUTPUT_DEVICE", "LANGUAGE_HEADPHONE_OUTPUT_DEVICE"),
    ),
    "headphone-isolation-guided-capture": Step(
        name="headphone-isolation-guided-capture",
        description="strict host-guided listener-ear capture and scoring",
        local_args=(
            "pwsh",
            "-NoProfile",
            "-File",
            "scripts/headphone_isolation_local.ps1",
            "-Action",
            "capture",
            "--measurement-input-device",
            "{env:LANGUAGE_MEASUREMENT_INPUT_DEVICE:LISTENER_EAR_INPUT}",
            "--source-output-device",
            "{env:LANGUAGE_SOURCE_OUTPUT_DEVICE:SOURCE_SPEAKER_OUTPUT}",
            "--headphone-output-device",
            "{env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE:HEADPHONE_OUTPUT}",
            "--preflight-report",
            "{env:LANGUAGE_CAPTURE_PREFLIGHT_REPORT:artifacts/audio_eval/runs/headphone-earpiece-preflight/headphone-preflight-report.json}",
            "--sample-rate-hz",
            "{env:LANGUAGE_AUDIO_SAMPLE_RATE_HZ:48000}",
            "--input-channels",
            "{env:LANGUAGE_AUDIO_INPUT_CHANNELS:1}",
            "--output-channels",
            "{env:LANGUAGE_AUDIO_OUTPUT_CHANNELS:2}",
            "--playback-gain-db",
            "{env:LANGUAGE_PLAYBACK_GAIN_DB:-18}",
            "--headphone-device-label",
            "{env:LANGUAGE_HEADPHONE_DEVICE_LABEL:REPLACE_WITH_HEADPHONE_MODEL}",
            "--isolation-fixture-label",
            "{env:LANGUAGE_ISOLATION_FIXTURE_LABEL:REPLACE_WITH_EARCUP_AND_MIC_POSITION}",
            "--measurement-microphone-label",
            "{env:LANGUAGE_MEASUREMENT_MICROPHONE_LABEL:REPLACE_WITH_MIC_MODEL_AND_POSITION}",
        ),
        required_env=(
            "LANGUAGE_MEASUREMENT_INPUT_DEVICE",
            "LANGUAGE_SOURCE_OUTPUT_DEVICE",
            "LANGUAGE_HEADPHONE_OUTPUT_DEVICE",
            "LANGUAGE_HEADPHONE_DEVICE_LABEL",
            "LANGUAGE_ISOLATION_FIXTURE_LABEL",
            "LANGUAGE_MEASUREMENT_MICROPHONE_LABEL",
        ),
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
            "release-progress-self-test",
            "release-checklist-contract",
            "gateway-package-verifier-self-test",
            "gateway-auth-smoke-self-test",
            "audio-contract-runner-self-test",
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
            "release-progress-self-test",
            "release-checklist-contract",
            "gateway-package-verifier-self-test",
            "gateway-auth-smoke-self-test",
            "audio-contract-runner-self-test",
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
    "smoke-local": Category(
        name="smoke-local",
        description="Fast local gateway demo smoke for health, session, and SSE baseline.",
        steps=("smoke-local-demo",),
        notes=(
            "Starts a temporary gateway if the configured port is free.",
            "Use GATEWAY_PORT when 8000 is already occupied.",
        ),
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
        handoff_log_steps=("headphone-route-triage-handoff",),
    ),
    "guided-capture": Category(
        name="guided-capture",
        description="Run the strict host-guided listener-ear capture path when devices and labels are ready.",
        steps=("headphone-isolation-guided-capture",),
        notes=(
            "Requires explicit LANGUAGE_* device and label environment variables.",
            "Requires a physically confirmed selected-route preflight report.",
            "Plays and records audio; keep it out of unattended runs.",
        ),
    ),
    "physical-audio-handoff": Category(
        name="physical-audio-handoff",
        description="One-command host-audio device snapshot, route, manual kit, and release checklist handoff.",
        steps=(
            "live-microphone-list-devices",
            "headphone-isolation-list-devices",
            "headphone-local-preflight",
            "headphone-route-triage-handoff",
            "headphone-isolation-collect-evidence",
            "headphone-isolation-check-manual",
            "release-audio-status",
        ),
        notes=(
            "Does not play probe audio, record audio, or score placeholder labels.",
            "Use before a hardware session to refresh the checklist and raw WAV dropbox.",
        ),
        success_hints=(
            "Physical checklist: artifacts/release/physical-audio-checklist.md",
            "Raw WAV dropbox: artifacts/audio_eval/runs/headphone-earpiece-manual-kit/raw-listener-ear-recordings",
        ),
        handoff_log_steps=("headphone-route-triage-handoff",),
        manual_status_report="artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-status.json",
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
        success_hints=(
            "Status handoff: artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-status.md",
            "Required WAV map: artifacts/audio_eval/runs/headphone-earpiece-manual-kit/raw-listener-ear-recordings/listener-ear-recording-dropbox.md",
        ),
        manual_status_report="artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-status.json",
    ),
    "reference-playback-dry-run": Category(
        name="reference-playback-dry-run",
        description="Validate the manual reference playback plan without playing audio.",
        steps=("headphone-isolation-playback-plan",),
        notes=(
            "Requires LANGUAGE_SOURCE_OUTPUT_DEVICE and LANGUAGE_HEADPHONE_OUTPUT_DEVICE.",
            "Writes the manual playback log with release_proof=false.",
        ),
    ),
    "recording-session-dry-run": Category(
        name="recording-session-dry-run",
        description="Prepare the listener-ear kit, validate playback routing without audio, and print release status.",
        steps=(
            "headphone-isolation-collect-evidence",
            "headphone-isolation-playback-plan",
            "headphone-isolation-check-manual",
            "release-audio-status",
        ),
        notes=(
            "Requires LANGUAGE_SOURCE_OUTPUT_DEVICE and LANGUAGE_HEADPHONE_OUTPUT_DEVICE.",
            "Does not play or record audio; use this before starting the external listener-ear recorder.",
        ),
        success_hints=(
            "Status handoff: artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-status.md",
            "Next real audio command: python scripts/run_test_category.py reference-playback",
        ),
        manual_status_report="artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-status.json",
    ),
    "reference-playback": Category(
        name="reference-playback",
        description="Play manual source/translated references for an external listener-ear recorder.",
        steps=("headphone-isolation-playback-session",),
        notes=(
            "Requires LANGUAGE_SOURCE_OUTPUT_DEVICE and LANGUAGE_HEADPHONE_OUTPUT_DEVICE.",
            "Plays audio; start the external recorder first. The playback log is not release evidence.",
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
        success_hints=(
            "Status handoff: artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-status.md",
            "Release status: artifacts/release/audio-gate-report.md",
        ),
        manual_status_report="artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-status.json",
    ),
    "release-evidence-score": Category(
        name="release-evidence-score",
        description="Import/check/score listener-ear evidence when WAVs and real labels are ready.",
        steps=(
            "headphone-isolation-collect-and-score-evidence",
            "release-audio-status",
        ),
        notes=(
            "Set LANGUAGE_HEADPHONE_DEVICE_LABEL, LANGUAGE_ISOLATION_FIXTURE_LABEL, and LANGUAGE_MEASUREMENT_MICROPHONE_LABEL first.",
            "Unset or placeholder labels keep the score blocked instead of creating release evidence.",
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
    "release-progress": Category(
        name="release-progress",
        description="Evidence-linked milestone percentages and total completion estimate.",
        steps=("release-progress",),
        notes=(
            "Use after each push to keep milestone percentages reproducible.",
            "The hard release gate remains authoritative for pass/fail.",
        ),
    ),
    "release-artifacts": Category(
        name="release-artifacts",
        description="Build clean local source/gateway artifacts and smoke the packaged gateway.",
        steps=("local-release-artifacts", "gateway-package-smoke"),
        notes=(
            "Refuses dirty trees by default because source archives are built from HEAD.",
            "Uses a supported Python >=3.11,<3.14 from -Python, LANGUAGE_PACKAGE_PYTHON, LANGUAGE_PYTHON, PYTHON, bundled runtime, or PATH.",
            "Writes dist/local-release-artifacts/manifest.md and SHA256SUMS.txt.",
            "Installs the built gateway wheel into a temporary virtualenv and verifies the packaged CLI serves the smoke and auth endpoints.",
        ),
    ),
    "all": Category(
        name="all",
        description="All automated non-interactive suites: quick, core, local smoke, and Docker audio fixtures.",
        includes=("quick", "core", "smoke-local", "audio-fixtures"),
        notes=(
            "Excludes hardware, guided-capture, release, optional-models, and artifact-dependent voice-candidates.",
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


def expand_arg_templates(args: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    for arg in args:
        if arg == "{python}":
            expanded.append(sys.executable)
            continue
        if arg == "{flutter}":
            expanded.append(resolve_flutter())
            continue
        match = ENV_ARG_PATTERN.match(arg)
        if match:
            name = match.group(1)
            default = match.group(2) or ""
            expanded.append(os.environ.get(name, default))
        else:
            expanded.append(arg)
    return expanded


def resolve_flutter() -> str:
    for name in ("LANGUAGE_FLUTTER", "FLUTTER"):
        candidate = os.environ.get(name, "").strip()
        if candidate:
            return candidate
    resolved = shutil.which("flutter")
    if resolved:
        return resolved
    if PORTABLE_FLUTTER.exists():
        return str(PORTABLE_FLUTTER)
    return "flutter"


def command_for_step(step: Step, runner: str) -> tuple[list[str], dict[str, str]]:
    if step.is_local:
        return expand_arg_templates(step.local_args), {}
    if not step.target:
        if runner == "powershell" and step.powershell_args:
            return expand_arg_templates(step.powershell_args), {}
        raise ValueError(f"step {step.name} has no local_args, powershell_args, or target")
    if runner == "make":
        return ["make", step.target], dict(step.make_env)
    if runner == "powershell":
        if step.powershell_args:
            return expand_arg_templates(step.powershell_args), {}
        return [
            "pwsh",
            "-NoProfile",
            "-File",
            DEV_CONTAINER,
            step.target,
            *expand_arg_templates(step.target_args),
        ], {}
    raise ValueError(f"unsupported runner for target step {step.name}: {runner}")


def format_command(command: Iterable[str], env_delta: dict[str, str]) -> str:
    env_prefix = " ".join(f"{key}={value!r}" for key, value in sorted(env_delta.items()))
    rendered = " ".join(command)
    return f"{env_prefix} {rendered}".strip()


def _placeholder_required_env(value: str) -> bool:
    text = value.strip()
    return (
        not text
        or text.upper() in PLACEHOLDER_REQUIRED_ENV_VALUES
        or text.upper().startswith("REPLACE_WITH_")
    )


def missing_required_env(step: Step) -> list[str]:
    return [name for name in step.required_env if _placeholder_required_env(os.environ.get(name, ""))]


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


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def manual_status_state(summary: dict[str, Any]) -> str:
    if bool(summary.get("manual_score_ready")):
        return "SCORE-READY"
    if bool(summary.get("manual_recordings_ready_for_score_input")):
        return "FILES-READY-LABELS-PENDING"
    return "NOT-READY"


def manual_status_summary_lines(report_path: str) -> list[str]:
    path = ROOT / report_path
    if not path.exists():
        return [f"Manual status summary unavailable: {repo_relative(path)} does not exist yet."]
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"Manual status summary unavailable: {exc}"]
    report = as_dict(report)
    summary = as_dict(report.get("summary"))
    requirements = as_dict(report.get("recording_requirements"))
    status = manual_status_state(summary)
    lines = [f"Status: {status}", f"Raw WAV dropbox: {MANUAL_RECORDING_DROPBOX}"]

    missing_keys: set[str] = set()
    for check in report.get("checks", []):
        check = as_dict(check)
        if check.get("name") != "manual_recording_wavs_ready":
            continue
        for name, details in as_dict(check.get("value")).items():
            details = as_dict(details)
            if not bool(details.get("exists")):
                missing_keys.add(str(name))
    missing = [
        MANUAL_RECORDING_FILENAMES[key]
        for key in MANUAL_RECORDING_FILENAMES
        if key in missing_keys
    ]
    if missing:
        lines.append(f"Missing WAVs: {', '.join(missing)}")

    sample_rate = requirements.get("sample_rate_hz")
    min_duration = requirements.get("min_duration_s")
    wav_format = str(requirements.get("format", "")).strip()
    requirement_parts = [
        part
        for part in (
            wav_format,
            f"{sample_rate} Hz" if sample_rate else "",
            f">= {min_duration:g}s" if isinstance(min_duration, (int, float)) else "",
        )
        if part
    ]
    if requirement_parts:
        lines.append(f"Required WAV shape: {', '.join(requirement_parts)}")

    placeholder_count = int(summary.get("placeholder_label_count", 0) or 0)
    if placeholder_count:
        lines.append(
            "Labels still needed: LANGUAGE_HEADPHONE_DEVICE_LABEL, "
            "LANGUAGE_ISOLATION_FIXTURE_LABEL, LANGUAGE_MEASUREMENT_MICROPHONE_LABEL"
        )
    if status == "NOT-READY":
        lines.append("Next: add missing WAVs, then run python scripts/run_test_category.py release-evidence")
    elif status == "FILES-READY-LABELS-PENDING":
        lines.append("Next: set concrete labels, then run python scripts/run_test_category.py release-evidence-score")
    else:
        lines.append("Next: run python scripts/run_test_category.py release-evidence-score")
    return lines


def list_categories() -> int:
    print("Available test categories:\n")
    for name in sorted(CATEGORIES):
        category = CATEGORIES[name]
        steps = resolve_category_steps(name)
        print(f"{name:18} {len(steps):2d} step(s)  {category.description}")
        for note in category.notes:
            print(f"{'':22}- {note}")
    return 0


def quiet_handoff_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if lines and lines[0].startswith("$ "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return lines[:80]


def run_category(args: argparse.Namespace) -> int:
    runner = choose_runner(args.runner)
    steps = resolve_category_steps(args.category)
    quiet_step_logs: dict[str, Path] = {}
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
            missing_env = missing_required_env(step)
            if missing_env:
                print(f"   requires concrete env: {', '.join(missing_env)}")
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
        missing_env = missing_required_env(step)
        if missing_env:
            print(f"{step.name} requires concrete environment variables: {', '.join(missing_env)}")
            print("Use --dry-run to inspect the command template before setting hardware values.")
            return 2
        if args.quiet:
            log_path = log_dir / f"{index:02d}-{safe_filename(step.name)}.log"
            quiet_step_logs[step.name] = log_path
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
    category = CATEGORIES[args.category]
    if category.success_hints:
        print("Handoff:")
        for hint in category.success_hints:
            print(f"- {hint}")
    if args.quiet and category.handoff_log_steps:
        print("Command handoff:")
        for step_name in category.handoff_log_steps:
            log_path = quiet_step_logs.get(step_name)
            if not log_path or not log_path.exists():
                print(f"- Handoff log unavailable for {step_name}.")
                continue
            for line in quiet_handoff_lines(log_path):
                print(line)
    if category.manual_status_report:
        print("Manual recording summary:")
        for line in manual_status_summary_lines(category.manual_status_report):
            print(f"- {line}")
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
    for excluded in (
        "hardware",
        "guided-capture",
        "reference-playback",
        "release",
        "optional-models",
        "voice-candidates",
    ):
        if excluded in CATEGORIES["all"].includes:
            raise AssertionError(f"all should not implicitly include {excluded}")
    handoff_steps = CATEGORIES["physical-audio-handoff"].steps
    expected_handoff_prefix = (
        "live-microphone-list-devices",
        "headphone-isolation-list-devices",
        "headphone-local-preflight",
    )
    if handoff_steps[: len(expected_handoff_prefix)] != expected_handoff_prefix:
        raise AssertionError("physical-audio-handoff must list host devices before route preflight")
    if CATEGORIES["reference-playback-dry-run"].steps != ("headphone-isolation-playback-plan",):
        raise AssertionError("reference-playback-dry-run must only validate the playback plan")
    if "headphone-isolation-playback-plan" not in CATEGORIES["recording-session-dry-run"].steps:
        raise AssertionError("recording-session-dry-run must validate playback routing without audio")
    if CATEGORIES["route-triage"].handoff_log_steps != ("headphone-route-triage-handoff",):
        raise AssertionError("route-triage must print the generated probe handoff in quiet mode")
    if CATEGORIES["physical-audio-handoff"].handoff_log_steps != ("headphone-route-triage-handoff",):
        raise AssertionError("physical-audio-handoff must include the route probe handoff in quiet mode")
    if not CATEGORIES["recording-status"].success_hints:
        raise AssertionError("recording-status must print where the manual status handoff was written")
    if not CATEGORIES["recording-status"].manual_status_report:
        raise AssertionError("recording-status must print a concise manual recording summary")
    recording_status_report = ROOT / CATEGORIES["recording-status"].manual_status_report
    if recording_status_report.exists():
        summary_text = "\n".join(manual_status_summary_lines(CATEGORIES["recording-status"].manual_status_report))
        for expected in ("Raw WAV dropbox:", "Next:"):
            if expected not in summary_text:
                raise AssertionError(f"recording-status summary must include {expected!r}")
    if CATEGORIES["reference-playback"].steps != ("headphone-isolation-playback-session",):
        raise AssertionError("reference-playback must only run the explicit playback session")
    score_required_env = (
        "LANGUAGE_HEADPHONE_DEVICE_LABEL",
        "LANGUAGE_ISOLATION_FIXTURE_LABEL",
        "LANGUAGE_MEASUREMENT_MICROPHONE_LABEL",
    )
    if STEPS["headphone-isolation-collect-and-score-evidence"].required_env != score_required_env:
        raise AssertionError("release-evidence-score must require concrete hardware labels")
    score_command, _ = command_for_step(STEPS["headphone-isolation-collect-and-score-evidence"], "powershell")
    rendered_score_command = " ".join(score_command)
    for placeholder in score_required_env:
        if placeholder not in rendered_score_command:
            raise AssertionError(f"release-evidence-score dry-run command must show {placeholder}")
    for playback_step in (
        STEPS["headphone-isolation-playback-plan"],
        STEPS["headphone-isolation-playback-session"],
    ):
        if playback_step.required_env != ("LANGUAGE_SOURCE_OUTPUT_DEVICE", "LANGUAGE_HEADPHONE_OUTPUT_DEVICE"):
            raise AssertionError(f"{playback_step.name} must require explicit source/headphone output devices")
        playback_command, _ = command_for_step(playback_step, "powershell")
        rendered_playback_command = " ".join(playback_command)
        for placeholder in ("LANGUAGE_SOURCE_OUTPUT_DEVICE", "LANGUAGE_HEADPHONE_OUTPUT_DEVICE"):
            if placeholder not in rendered_playback_command:
                raise AssertionError(f"{playback_step.name} dry-run command must show {placeholder}")
    old_env = {name: os.environ.get(name) for name in score_required_env}
    os.environ["LANGUAGE_HEADPHONE_DEVICE_LABEL"] = "REPLACE_WITH_HEADPHONE_MODEL"
    os.environ["LANGUAGE_ISOLATION_FIXTURE_LABEL"] = "LANGUAGE_ISOLATION_FIXTURE_LABEL"
    os.environ["LANGUAGE_MEASUREMENT_MICROPHONE_LABEL"] = "LANGUAGE_MEASUREMENT_MICROPHONE_LABEL"
    try:
        missing_score_env = missing_required_env(STEPS["headphone-isolation-collect-and-score-evidence"])
        for placeholder in score_required_env:
            if placeholder not in missing_score_env:
                raise AssertionError(f"placeholder label must be rejected as missing: {placeholder}")
    finally:
        for name, value in old_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    for step in STEPS.values():
        for name in step.required_env:
            if not re.match(r"^[A-Z][A-Z0-9_]*$", name):
                raise AssertionError(f"invalid required env name on {step.name}: {name}")
    if not parse_args(["--list"]).list:
        raise AssertionError("--list must be accepted as a category listing alias")
    if parse_args(["list"]).category != "list":
        raise AssertionError("positional list category must remain available")
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
    parser.add_argument("--list", action="store_true", help="show categories and exit")
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
    if args.list or args.category == "list":
        return list_categories()
    return run_category(args)


if __name__ == "__main__":
    raise SystemExit(main())
