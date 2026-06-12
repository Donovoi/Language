#!/usr/bin/env python3
"""Generate a Robin-oriented research pack for Language implementation choices."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS_PATH = ROOT_DIR / "research" / "language_stack_questions.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "docs" / "research" / "runs"
DEFAULT_ROBIN_REPO = ROOT_DIR.parent / "robin"

REQUIRED_FIELDS = {
    "id",
    "decision",
    "implementation_surface",
    "robin_task",
    "queries",
    "metrics",
    "benchmark_fixture",
    "acceptance_gate",
    "detractor_focus",
}

SEED_PRIMARY_SOURCES = [
    {
        "title": "Robin: A multi-agent system for automating scientific discovery",
        "status": "peer-reviewed Nature article; use as research-workflow precedent",
        "url": "https://www.nature.com/articles/s41586-026-10652-y",
    },
    {
        "title": "Joint speech and text machine translation for up to 100 languages",
        "status": "peer-reviewed Nature article; SEAMLESSM4T speech translation baseline",
        "url": "https://www.nature.com/articles/s41586-024-08359-z",
    },
    {
        "title": "Streaming Sortformer: Speaker Cache-Based Online Speaker Diarization with Arrival-Time Ordering",
        "status": "Interspeech 2025; streaming diarization seed",
        "url": "https://www.isca-archive.org/interspeech_2025/medennikov25_interspeech.pdf",
    },
    {
        "title": "DIARIST: Streaming Speech Translation with Speaker Diarization",
        "status": "ICASSP 2024; streaming speech translation plus diarization seed",
        "url": "https://www.microsoft.com/en-us/research/uploads/prod/2024/05/ICASSP2024_Translation_and_Diarization.pdf",
    },
    {
        "title": "TIGER: Time-frequency Interleaved Gain Extraction and Reconstruction for Efficient Speech Separation",
        "status": "ICLR 2025; efficient speech separation seed",
        "url": "https://proceedings.iclr.cc/paper_files/paper/2025/hash/af790b7ae573771689438bbcfc5933fe-Abstract-Conference.html",
    },
    {
        "title": "TF-MLPNet: Tiny Real-Time Neural Speech Separation",
        "status": "Clarity 2025; tiny real-time separation seed",
        "url": "https://www.isca-archive.org/clarity_2025/itani25_clarity.html",
    },
    {
        "title": "pyannote.audio 2.1 speaker diarization pipeline: principle, benchmark, and recipe",
        "status": "Interspeech 2023; open diarization toolkit baseline",
        "url": "https://www.isca-archive.org/interspeech_2023/bredin23_interspeech.html",
    },
    {
        "title": "Robust Speech Recognition via Large-Scale Weak Supervision",
        "status": "ICML 2023; Whisper multilingual ASR baseline",
        "url": "https://proceedings.mlr.press/v202/radford23a.html",
    },
    {
        "title": "High fidelity zero shot speaker adaptation in text to speech synthesis with denoising diffusion GAN",
        "status": "Scientific Reports 2025; zero-shot speaker-adaptive TTS seed",
        "url": "https://pubmed.ncbi.nlm.nih.gov/39979408/",
    },
    {
        "title": "SLM-S2ST: A multimodal language model for direct speech-to-speech translation",
        "status": "2025 arXiv preprint; label as unreviewed until venue status changes",
        "url": "https://www.microsoft.com/en-us/research/publication/slm-s2st-a-multimodal-language-model-for-direct-speech-to-speech-translation/",
    },
]


def main() -> int:
    args = parse_args()
    questions_path = Path(args.questions).resolve()
    data = load_questions(questions_path)
    questions = validate_questions(data, questions_path)

    robin_repo = Path(
        args.robin_repo
        or os.getenv("ROBIN_REPO_PATH")
        or DEFAULT_ROBIN_REPO
    ).resolve()

    if args.check:
        print(
            f"Research pack check passed: {len(questions)} questions in "
            f"{questions_path}"
        )
        return 0

    run_id = args.run_id or default_run_id()
    output_dir = Path(args.output_dir).resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "research-pack.md"
    output_path.write_text(
        render_pack(data, questions, run_id=run_id, robin_repo=robin_repo),
        encoding="utf-8",
    )
    print(output_path)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a dated Robin research pack for Language stack decisions."
    )
    parser.add_argument(
        "--questions",
        default=str(DEFAULT_QUESTIONS_PATH),
        help="Path to the Language research question matrix.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where dated research packs are written.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional stable run id. Defaults to the current UTC timestamp.",
    )
    parser.add_argument(
        "--robin-repo",
        help=(
            "Path to the local Robin checkout. Defaults to ROBIN_REPO_PATH or "
            "../robin beside this repo."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the question matrix without writing a research pack.",
    )
    return parser.parse_args()


def load_questions(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise SystemExit(f"Research question file not found: {path}") from err
    except json.JSONDecodeError as err:
        raise SystemExit(f"Invalid JSON in {path}: {err}") from err


def validate_questions(data: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    if data.get("schema_version") != 1:
        raise SystemExit(f"{path} must declare schema_version 1")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise SystemExit(f"{path} must contain a non-empty questions list")
    detractor_loop = data.get("detractor_loop")
    if not isinstance(detractor_loop, dict):
        raise SystemExit(f"{path} must contain a detractor_loop object")
    for field_name in ["required_questions", "minimum_output"]:
        values = detractor_loop.get(field_name)
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip() for value in values
        ):
            raise SystemExit(
                f"detractor_loop.{field_name} must be a non-empty string list"
            )

    seen_ids: set[str] = set()
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            raise SystemExit(f"Question {index} must be an object")
        missing = sorted(REQUIRED_FIELDS - set(question))
        if missing:
            raise SystemExit(f"Question {index} is missing fields: {missing}")
        question_id = str(question["id"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", question_id):
            raise SystemExit(f"Question {index} has invalid id: {question_id}")
        if question_id in seen_ids:
            raise SystemExit(f"Duplicate question id: {question_id}")
        seen_ids.add(question_id)
        for field_name in ["queries", "metrics"]:
            values = question[field_name]
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise SystemExit(
                    f"Question {question_id} field {field_name} must be a "
                    "non-empty string list"
                )
    return questions


def default_run_id() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ-language-stack")


def render_pack(
    data: dict[str, Any],
    questions: list[dict[str, Any]],
    *,
    run_id: str,
    robin_repo: Path,
) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    robin_exists = robin_repo.exists()
    robin_display = display_path(robin_repo)
    lines: list[str] = [
        "# Language Research Pack",
        "",
        f"- Run id: `{run_id}`",
        f"- Generated: `{generated_at}`",
        f"- Robin checkout: `{robin_display}`",
        f"- Robin checkout detected: `{str(robin_exists).lower()}`",
        f"- App goal: {data['app_goal']}",
        "",
        "## How To Use This Pack",
        "",
        "1. Start Robin from the local checkout and use the open literature backend unless Edison is explicitly configured.",
        "2. For each subsystem below, run Robin against the task and queries, then verify high-impact claims against primary sources.",
        "3. Write an implementation decision record using `docs/research/decision-record-template.md`.",
        "4. Add the smallest disposable benchmark or smoke check before wiring the chosen candidate into runtime code.",
        "",
        "Suggested Robin setup:",
        "",
        "```powershell",
        f"cd {robin_display}",
        "docker compose -f docker-compose.search.yml up -d",
        "$env:ROBIN_LITERATURE_BACKEND = \"open\"",
        "$env:ROBIN_WEB_SEARCH_URL = \"http://127.0.0.1:8080/search\"",
        "```",
        "",
        "Use SearXNG for lead discovery only. The decision record must cite primary papers, official model cards, or official benchmark docs.",
        "",
        "## Evidence Standard",
        "",
    ]

    evidence_standard = data["evidence_standard"]
    lines.extend(render_bullets("Preferred", evidence_standard["preferred"]))
    lines.extend(render_bullets("Allowed With Label", evidence_standard["allowed_with_label"]))
    lines.extend(render_bullets("Required For Decision", evidence_standard["required_for_decision"]))
    lines.extend(render_detractor_loop(data["detractor_loop"]))

    lines.extend(
        [
            "## Seed Primary Sources",
            "",
            "These are starting points, not final authority. Refresh them before each decision.",
            "",
        ]
    )
    for source in SEED_PRIMARY_SOURCES:
        lines.append(
            f"- [{source['title']}]({source['url']}) - {source['status']}"
        )
    lines.append("")

    lines.extend(["## Research Questions", ""])
    for question in questions:
        lines.extend(render_question(question))

    lines.extend(
        [
            "## Decision Output Checklist",
            "",
            "- best option and runner-up",
            "- why this app's constraints favor the selected option",
            "- peer-reviewed or primary-source evidence table",
            "- preprints and vendor claims clearly labeled",
            "- benchmark command, fixture, and disposable environment notes",
            "- rollback or fallback behavior",
            "- contract fields affected in `proto/session.proto`",
            "",
        ]
    )
    return "\n".join(lines)


def display_path(path: Path) -> str:
    try:
        return os.path.relpath(path, ROOT_DIR)
    except ValueError:
        return str(path)


def render_bullets(title: str, values: list[str]) -> list[str]:
    lines = [f"### {title}", ""]
    lines.extend(f"- {value}" for value in values)
    lines.append("")
    return lines


def render_question(question: dict[str, Any]) -> list[str]:
    lines = [
        f"### {question['id']}",
        "",
        f"- Decision: {question['decision']}",
        f"- Implementation surface: {question['implementation_surface']}",
        f"- Robin task: {question['robin_task']}",
        f"- Benchmark fixture: {question['benchmark_fixture']}",
        f"- Acceptance gate: {question['acceptance_gate']}",
        f"- Detractor focus: {question['detractor_focus']}",
        "",
        "Queries:",
        "",
    ]
    lines.extend(f"- {query}" for query in question["queries"])
    lines.extend(["", "Metrics:", ""])
    lines.extend(f"- {metric}" for metric in question["metrics"])
    lines.append("")
    return lines


def render_detractor_loop(detractor_loop: dict[str, Any]) -> list[str]:
    lines = [
        "## Detractor Loop",
        "",
        detractor_loop["purpose"],
        "",
        "Required skeptic questions:",
        "",
    ]
    lines.extend(f"- {question}" for question in detractor_loop["required_questions"])
    lines.extend(["", "Minimum detractor output:", ""])
    lines.extend(f"- {item}" for item in detractor_loop["minimum_output"])
    lines.append("")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
