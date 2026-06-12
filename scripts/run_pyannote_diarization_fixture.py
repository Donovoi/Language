#!/usr/bin/env python3
"""Run pyannote diarization on audio-eval fixtures and write scorer JSONL."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from audio_eval_harness import (
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT_DIR,
    render_fixtures,
    safe_id,
    score_diarization_predictions,
    write_jsonl,
    write_report,
)


DEFAULT_MODEL = "pyannote/speaker-diarization-community-1"
DEFAULT_RUN_ID = "pyannote-community-1"


def load_pyannote_pipeline(model: str, token: str | None, device: str) -> Any:
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise SystemExit(
            "pyannote.audio is not installed. Install optional dependencies inside the "
            "audio-eval container with: python3 -m pip install -r "
            "docker/dev/requirements-audio-eval-pyannote.txt"
        ) from exc

    pipeline = Pipeline.from_pretrained(model, token=token)
    if pipeline is None:
        raise SystemExit(
            "pyannote Pipeline.from_pretrained returned None. Check model access conditions, "
            "HF_TOKEN/HUGGINGFACE_TOKEN, and local model path."
        )

    if device != "cpu":
        try:
            import torch
        except ImportError as exc:
            raise SystemExit("GPU device requested but torch is not importable.") from exc
        pipeline.to(torch.device(device))

    return pipeline


def env_token() -> tuple[str | None, str | None]:
    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value, name
    return None, None


def should_require_token(model: str) -> bool:
    model_path = Path(model)
    return model.startswith("pyannote/") and not model_path.exists()


def fixture_mix_path(output_dir: Path, annotation: dict[str, Any]) -> Path:
    return (
        output_dir
        / "fixtures"
        / annotation["fixture_set_id"]
        / safe_id(annotation["fixture_id"])
        / annotation["mix_path"]
    )


def human_speaker_count(annotation: dict[str, Any]) -> int:
    return len(
        {
            segment["speaker_id"]
            for segment in annotation["segments"]
            if segment["source_kind"] == "human"
        }
    )


def extract_diarization(output: Any, use_exclusive: bool) -> Any:
    if use_exclusive and hasattr(output, "exclusive_speaker_diarization"):
        return output.exclusive_speaker_diarization
    if hasattr(output, "speaker_diarization"):
        return output.speaker_diarization
    return output


def diarization_segments(diarization: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append(
            {
                "speaker_id": str(speaker),
                "start_s": round(float(turn.start), 6),
                "end_s": round(float(turn.end), 6),
                "confidence": 1.0,
            }
        )
    return sorted(segments, key=lambda item: (item["start_s"], item["end_s"], item["speaker_id"]))


def run_fixture(
    pipeline: Any,
    annotation: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    mix_path = fixture_mix_path(output_dir, annotation)
    kwargs: dict[str, Any] = {}
    if args.num_speakers_from_truth:
        kwargs["num_speakers"] = human_speaker_count(annotation)
    if args.min_speakers is not None:
        kwargs["min_speakers"] = args.min_speakers
    if args.max_speakers is not None:
        kwargs["max_speakers"] = args.max_speakers

    started = time.perf_counter()
    output = pipeline(str(mix_path), **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    diarization = extract_diarization(output, args.exclusive)

    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": args.adapter_id,
        "segments": diarization_segments(diarization),
        "model_layer_latency_ms": {
            "diarization": round(elapsed_ms, 3),
        },
        "metadata": {
            "model": args.model,
            "device": args.device,
            "exclusive": bool(args.exclusive),
            "num_speakers_from_truth": bool(args.num_speakers_from_truth),
            "min_speakers": args.min_speakers,
            "max_speakers": args.max_speakers,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pyannote diarization on audio-eval fixtures")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--adapter-id")
    parser.add_argument("--hf-token")
    parser.add_argument("--allow-no-token", action="store_true")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--exclusive", action="store_true")
    parser.add_argument("--num-speakers-from-truth", action="store_true")
    parser.add_argument("--min-speakers", type=int)
    parser.add_argument("--max-speakers", type=int)
    parser.add_argument("--no-score", action="store_true")
    parser.add_argument("--score-warning-only", action="store_true")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest_path = args.manifest.resolve()
    output_dir = args.output_dir.resolve()
    if args.adapter_id is None:
        args.adapter_id = args.run_id
    predictions_path = (
        args.predictions.resolve()
        if args.predictions
        else output_dir / "runs" / args.run_id / "predictions.jsonl"
    )
    report_path = (
        args.report.resolve()
        if args.report
        else output_dir / "runs" / args.run_id / "diarization-score-report.json"
    )

    token = args.hf_token
    token_source = "argument" if token else None
    if not token:
        token, token_source = env_token()
    if should_require_token(args.model) and not token and not args.allow_no_token:
        raise SystemExit(
            "pyannote Community-1 requires accepting Hugging Face model conditions and setting "
            "HF_TOKEN or HUGGINGFACE_TOKEN. Use --allow-no-token only for a local/offline model path."
        )

    annotations = render_fixtures(manifest_path, output_dir)
    pipeline = load_pyannote_pipeline(args.model, token, args.device)
    records = [run_fixture(pipeline, annotation, output_dir, args) for annotation in annotations]
    for record in records:
        record["metadata"]["token_source"] = token_source or "none"
    write_jsonl(records, predictions_path)
    print(f"wrote pyannote diarization predictions to {predictions_path}")

    if args.no_score:
        return 0

    report = score_diarization_predictions(annotations, predictions_path, strict_oracle=False)
    report["detractor_loop"]["strongest_objection"] = (
        "pyannote Community-1 is an offline baseline here. Synthetic tone fixtures and CPU runtime "
        "do not prove real-time overlapping-speaker performance."
    )
    write_report(report, report_path)
    print(f"wrote pyannote diarization score report to {report_path}")

    passed = all(bool(gate["passed"]) for gate in report["summary"]["quality_gates"])
    if not passed and args.score_warning_only:
        print("pyannote score gates failed, but --score-warning-only was set")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
