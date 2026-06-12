#!/usr/bin/env python3
"""Run NVIDIA Sortformer diarization on the tiny real-speech overlap fixture."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from audio_eval_harness import DEFAULT_OUTPUT_DIR, score_diarization_predictions, write_jsonl, write_report
from prepare_real_speech_fixture import (
    DEFAULT_CONFIG,
    DEFAULT_DATASET,
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    DEFAULT_SAMPLE_RATE_HZ,
    prepare_real_speech_fixture,
)
from run_pyannote_diarization_fixture import fixture_mix_path


DEFAULT_MODEL = "nvidia/diar_streaming_sortformer_4spk-v2.1"
DEFAULT_RUN_ID = "sortformer-streaming-4spk-v2-1-real-speech"


def env_token() -> tuple[str | None, str | None]:
    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value, name
    return None, None


def should_require_token(model: str, model_path: Path | None) -> bool:
    if model_path is not None:
        return False
    candidate = Path(model)
    return model.startswith("nvidia/") and not candidate.exists()


def load_sortformer_model(
    model: str,
    model_path: Path | None,
    token: str | None,
    device: str,
) -> Any:
    try:
        from nemo.collections.asr.models import SortformerEncLabelModel
    except ImportError as exc:
        raise SystemExit(
            "NVIDIA NeMo is not installed. Use the audio-eval-sortformer Docker profile "
            "or install docker/dev/requirements-audio-eval-sortformer.txt."
        ) from exc

    if token:
        os.environ.setdefault("HF_TOKEN", token)
        os.environ.setdefault("HUGGINGFACE_TOKEN", token)
        os.environ.setdefault("HUGGINGFACE_HUB_TOKEN", token)
        try:
            from huggingface_hub import login

            login(token=token, add_to_git_credential=False)
        except Exception:
            pass

    if model_path is not None:
        diar_model = SortformerEncLabelModel.restore_from(
            restore_path=str(model_path),
            map_location=device,
            strict=False,
        )
    else:
        diar_model = SortformerEncLabelModel.from_pretrained(model)

    diar_model.eval()
    if device != "cpu" and hasattr(diar_model, "to"):
        try:
            import torch
        except ImportError as exc:
            raise SystemExit("GPU device requested but torch is not importable.") from exc
        diar_model.to(torch.device(device))
    return diar_model


def _is_floatish(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _speaker_id(value: Any) -> str:
    if isinstance(value, int):
        return f"SPEAKER_{value:02d}"
    text = str(value).strip()
    if text.isdigit():
        return f"SPEAKER_{int(text):02d}"
    return text


def _segment_from_mapping(item: dict[str, Any]) -> dict[str, Any] | None:
    start = item.get("start_s", item.get("start", item.get("begin", item.get("begin_seconds"))))
    end = item.get("end_s", item.get("end", item.get("end_seconds")))
    if end is None and item.get("duration_s") is not None and start is not None:
        end = float(start) + float(item["duration_s"])
    if start is None or end is None:
        return None
    speaker = item.get(
        "speaker_id",
        item.get("speaker_label", item.get("speaker", item.get("speaker_index", item.get("label")))),
    )
    if speaker is None:
        return None
    confidence = float(item.get("confidence", item.get("score", 1.0)))
    return {
        "speaker_id": _speaker_id(speaker),
        "start_s": round(float(start), 6),
        "end_s": round(float(end), 6),
        "confidence": confidence,
    }


def _segment_from_sequence(item: list[Any] | tuple[Any, ...]) -> dict[str, Any] | None:
    if len(item) < 3 or not _is_floatish(item[0]) or not _is_floatish(item[1]):
        return None
    return {
        "speaker_id": _speaker_id(item[2]),
        "start_s": round(float(item[0]), 6),
        "end_s": round(float(item[1]), 6),
        "confidence": float(item[3]) if len(item) > 3 and _is_floatish(item[3]) else 1.0,
    }


def _segment_from_text(item: str) -> dict[str, Any] | None:
    parts = [part for part in item.replace(",", " ").split() if part]
    if len(parts) >= 8 and parts[0].upper() == "SPEAKER" and _is_floatish(parts[3]) and _is_floatish(parts[4]):
        start = float(parts[3])
        return {
            "speaker_id": _speaker_id(parts[7]),
            "start_s": round(start, 6),
            "end_s": round(start + float(parts[4]), 6),
            "confidence": 1.0,
        }

    numeric_indices = [index for index, part in enumerate(parts) if _is_floatish(part)]
    if len(numeric_indices) < 2:
        return None
    start_index, end_index = numeric_indices[0], numeric_indices[1]
    speaker = next(
        (parts[index] for index in range(end_index + 1, len(parts)) if not _is_floatish(parts[index])),
        parts[-1] if parts else "SPEAKER_00",
    )
    return {
        "speaker_id": _speaker_id(speaker),
        "start_s": round(float(parts[start_index]), 6),
        "end_s": round(float(parts[end_index]), 6),
        "confidence": 1.0,
    }


def _looks_like_segment(item: Any) -> bool:
    if isinstance(item, str):
        return _segment_from_text(item) is not None
    if isinstance(item, dict):
        return _segment_from_mapping(item) is not None
    if isinstance(item, (list, tuple)):
        return _segment_from_sequence(item) is not None
    return False


def _flatten_single_batch(output: Any) -> list[Any]:
    if isinstance(output, tuple):
        output = output[0]
    if isinstance(output, list) and len(output) == 1 and isinstance(output[0], list):
        first = output[0]
        if not _looks_like_segment(first):
            return list(first)
    if isinstance(output, list):
        return output
    return [output]


def sortformer_segments(output: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for item in _flatten_single_batch(output):
        segment: dict[str, Any] | None
        if isinstance(item, str):
            segment = _segment_from_text(item)
        elif isinstance(item, dict):
            segment = _segment_from_mapping(item)
        elif isinstance(item, (list, tuple)):
            segment = _segment_from_sequence(item)
        else:
            segment = None
        if segment is None:
            continue
        if float(segment["end_s"]) <= float(segment["start_s"]):
            continue
        segments.append(segment)
    return sorted(segments, key=lambda item: (item["start_s"], item["end_s"], item["speaker_id"]))


def run_fixture(
    diar_model: Any,
    annotation: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    mix_path = fixture_mix_path(output_dir, annotation)
    started = time.perf_counter()
    output = diar_model.diarize(audio=[str(mix_path)], batch_size=args.batch_size)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": args.adapter_id,
        "segments": sortformer_segments(output),
        "model_layer_latency_ms": {
            "diarization": round(elapsed_ms, 3),
        },
        "metadata": {
            "model": args.model,
            "model_path": None if args.model_path is None else str(args.model_path),
            "device": args.device,
            "batch_size": args.batch_size,
            "fixture_kind": "real_speech_mixed_overlap",
            "sample_rate_hz": DEFAULT_SAMPLE_RATE_HZ,
            "max_speakers": 4,
            "nemo_entrypoint": "SortformerEncLabelModel.diarize",
        },
    }


def run_self_test() -> int:
    cases: list[tuple[Any, list[dict[str, Any]]]] = [
        (
            [["0.2 1.4 speaker_0", "1.4, 2.0, 1"]],
            [
                {"speaker_id": "speaker_0", "start_s": 0.2, "end_s": 1.4, "confidence": 1.0},
                {"speaker_id": "SPEAKER_01", "start_s": 1.4, "end_s": 2.0, "confidence": 1.0},
            ],
        ),
        (
            [
                {"speaker": "talker-b", "start": 0.5, "end": 1.1, "score": 0.7},
                (1.1, 1.7, 2, 0.9),
            ],
            [
                {"speaker_id": "talker-b", "start_s": 0.5, "end_s": 1.1, "confidence": 0.7},
                {"speaker_id": "SPEAKER_02", "start_s": 1.1, "end_s": 1.7, "confidence": 0.9},
            ],
        ),
        (
            "SPEAKER file 1 0.500 0.700 <NA> <NA> speaker_3 <NA> <NA>",
            [
                {"speaker_id": "speaker_3", "start_s": 0.5, "end_s": 1.2, "confidence": 1.0},
            ],
        ),
    ]
    for output, expected in cases:
        actual = sortformer_segments(output)
        if actual != expected:
            print(f"sortformer adapter self-test FAIL: {actual!r} != {expected!r}")
            return 1
    print("sortformer adapter self-test PASS")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NVIDIA Sortformer on a tiny real-speech fixture")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--adapter-id")
    parser.add_argument("--hf-token")
    parser.add_argument("--allow-no-token", action="store_true")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--no-score", action="store_true")
    parser.add_argument("--score-warning-only", action="store_true")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        return run_self_test()

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
    if should_require_token(args.model, args.model_path) and not token and not args.allow_no_token:
        raise SystemExit(
            "NVIDIA Sortformer model downloads require a Hugging Face token. Set HF_TOKEN or "
            "HUGGINGFACE_TOKEN, pass --hf-token, or use --model-path for a local .nemo checkpoint."
        )

    annotation = prepare_real_speech_fixture(
        output_dir=output_dir,
        dataset=args.dataset,
        config=args.config,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        sample_rate_hz=args.sample_rate_hz,
    )
    annotations = [annotation]
    diar_model = load_sortformer_model(args.model, args.model_path, token, args.device)
    records = [run_fixture(diar_model, annotation, output_dir, args)]
    for record in records:
        record["metadata"]["token_source"] = token_source or "none"
    write_jsonl(records, predictions_path)
    print(f"wrote Sortformer real-speech predictions to {predictions_path}")

    if args.no_score:
        return 0

    report = score_diarization_predictions(annotations, predictions_path, strict_oracle=False)
    report["detractor_loop"]["strongest_objection"] = (
        "This exercises Sortformer through NeMo's direct diarize() entrypoint on one clean "
        "LibriSpeech mix. It does not prove causal microphone streaming, non-English robustness, "
        "or same-voice translated playback."
    )
    report["detractor_loop"]["cheapest_falsifying_benchmark"] = (
        "Run the same adapter on a consented local room recording with real overlap, measured "
        "source levels, and at least one non-English speaker."
    )
    report["detractor_loop"]["fallback_if_falsified"] = (
        "Keep Sortformer behind the benchmark adapter boundary and continue using pyannote or "
        "manual speaker lanes until local DER/JER/latency improve."
    )
    write_report(report, report_path)
    print(f"wrote Sortformer real-speech score report to {report_path}")

    passed = all(bool(gate["passed"]) for gate in report["summary"]["quality_gates"])
    if not passed and args.score_warning_only:
        print("Sortformer real-speech score gates failed, but --score-warning-only was set")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
