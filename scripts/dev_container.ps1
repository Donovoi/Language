param(
    [ValidateSet("build", "check", "release-audio-gate", "live-microphone-capture-list-devices", "live-microphone-capture-check", "real-room-playback-suppression-list-devices", "real-room-playback-suppression-contract-check", "headphone-isolation-contract-check", "headphone-isolation-list-devices", "headphone-isolation-probe-route", "headphone-isolation-sweep-routes", "headphone-isolation-virtual-lab", "headphone-isolation-prepare-manual", "headphone-isolation-check-manual", "headphone-isolation-play-manual", "headphone-isolation-import-manual", "headphone-isolation-score-manual", "headphone-isolation-capture", "headphone-isolation-score", "real-room-playback-suppression-probe-route", "real-room-playback-suppression-sweep-routes", "real-room-playback-suppression-qualify-device", "real-room-playback-suppression-sweep-devices", "real-room-playback-suppression-check", "shell", "destroy", "purge", "audio-eval-build", "audio-eval-check", "audio-eval-real-speech-check", "audio-eval-real-speech-chunked-check", "audio-eval-crowd-noise-check", "audio-eval-translation-check", "audio-eval-live-capture-contract-check", "audio-eval-live-capture-check", "audio-eval-playback-suppression-contract-check", "audio-eval-playback-suppression-check", "audio-eval-fallback-tts-contract-check", "audio-eval-fallback-tts-check", "audio-eval-oracle-tse-contract-check", "audio-eval-oracle-tse-check", "audio-eval-mixture-passthrough-tse-contract-check", "audio-eval-mixture-passthrough-tse-check", "audio-eval-enrolled-tse-contract-check", "audio-eval-enrolled-oracle-tse-check", "audio-eval-enrolled-mismatch-tse-check", "audio-eval-shell", "audio-eval-purge", "audio-eval-pyannote-build", "audio-eval-pyannote-check", "audio-eval-pyannote-real-speech-check", "audio-eval-pyannote-real-speech-chunked-check", "audio-eval-pyannote-shell", "audio-eval-pyannote-purge", "audio-eval-sortformer-build", "audio-eval-sortformer-contract-check", "audio-eval-sortformer-real-speech-check", "audio-eval-sortformer-real-speech-chunked-check", "audio-eval-sortformer-online-real-speech-check", "audio-eval-sortformer-rolling-real-speech-check", "audio-eval-sortformer-rolling-fleurs-check", "audio-eval-sortformer-shell", "audio-eval-sortformer-purge", "audio-eval-whisper-build", "audio-eval-whisper-contract-check", "audio-eval-whisper-translation-check", "audio-eval-whisper-rolling-contract-check", "audio-eval-whisper-rolling-translation-check", "audio-eval-whisper-oracle-tse-contract-check", "audio-eval-whisper-oracle-tse-translation-check", "audio-eval-whisper-mixture-passthrough-tse-contract-check", "audio-eval-whisper-mixture-passthrough-tse-translation-check", "audio-eval-whisper-causal-tse-contract-check", "audio-eval-whisper-speechbrain-sepformer-translation-check", "audio-eval-whisper-enrolled-oracle-tse-translation-check", "audio-eval-whisper-wesep-translation-check", "audio-eval-whisper-wesep-causal-translation-check", "audio-eval-whisper-shell", "audio-eval-whisper-purge", "audio-eval-speechbrain-sepformer-build", "audio-eval-speechbrain-sepformer-contract-check", "audio-eval-speechbrain-sepformer-check", "audio-eval-speechbrain-sepformer-shell", "audio-eval-speechbrain-sepformer-purge", "audio-eval-wesep-build", "audio-eval-wesep-contract-check", "audio-eval-wesep-check", "audio-eval-wesep-shell", "audio-eval-wesep-purge")]
    [string] $Action = "check",

    [string] $ComposeFile = "docker/dev/compose.yml",

    [string] $Image = "language-core-dev:local",

    [string] $AudioEvalImage = "language-audio-eval-dev:local",

    [string] $AudioEvalPyannoteImage = "language-audio-eval-pyannote-dev:local",

    [string] $AudioEvalSortformerImage = "language-audio-eval-sortformer-dev:local",

    [string] $AudioEvalWhisperImage = "language-audio-eval-whisper-dev:local",

    [string] $AudioEvalSpeechBrainSepformerImage = "language-audio-eval-speechbrain-sepformer-dev:local",

    [string] $AudioEvalWesepImage = "language-audio-eval-wesep-dev:local",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CommandArgs
)

$ErrorActionPreference = "Stop"
$env:DEV_IMAGE = $Image
$env:AUDIO_EVAL_IMAGE = $AudioEvalImage
$env:AUDIO_EVAL_PYANNOTE_IMAGE = $AudioEvalPyannoteImage
$env:AUDIO_EVAL_SORTFORMER_IMAGE = $AudioEvalSortformerImage
$env:AUDIO_EVAL_WHISPER_IMAGE = $AudioEvalWhisperImage
$env:AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE = $AudioEvalSpeechBrainSepformerImage
$env:AUDIO_EVAL_WESEP_IMAGE = $AudioEvalWesepImage

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Args)

    & docker compose -f $ComposeFile @Args
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

function Remove-ImageIfPresent {
    param([string] $Name)

    & docker image inspect $Name *> $null
    if ($LASTEXITCODE -eq 0) {
        & docker image rm $Name
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    } else {
        Write-Host "Image $Name is already absent."
    }
}

switch ($Action) {
    "build" {
        Invoke-Compose build core
    }
    "check" {
        Invoke-Compose run --rm core bash scripts/dev_container_check.sh
    }
    "release-audio-gate" {
        & python scripts/release_audio_gate.py
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "live-microphone-capture-list-devices" {
        & python scripts/run_live_microphone_capture.py list-devices
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "live-microphone-capture-check" {
        & python scripts/run_live_microphone_capture.py check
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "real-room-playback-suppression-list-devices" {
        & python scripts/run_real_room_playback_suppression.py list-devices
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "real-room-playback-suppression-contract-check" {
        & python scripts/run_real_room_playback_suppression.py self-test
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-contract-check" {
        & python scripts/run_headphone_isolation_check.py self-test
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-list-devices" {
        & python scripts/run_headphone_isolation_check.py list-devices
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-probe-route" {
        $probeArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py probe-route @probeArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-sweep-routes" {
        $sweepArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py sweep-routes @sweepArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-virtual-lab" {
        $virtualLabArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py virtual-lab @virtualLabArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-prepare-manual" {
        $manualArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py prepare-manual @manualArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-check-manual" {
        $checkManualArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py check-manual @checkManualArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-play-manual" {
        $playManualArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py play-manual @playManualArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-import-manual" {
        $importManualArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py import-manual @importManualArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-score-manual" {
        $scoreManualArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py score-manual @scoreManualArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-capture" {
        $captureArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py capture @captureArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "headphone-isolation-score" {
        $scoreArgs = $CommandArgs
        & python scripts/run_headphone_isolation_check.py score @scoreArgs
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "real-room-playback-suppression-probe-route" {
        & python scripts/run_real_room_playback_suppression.py probe-route
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "real-room-playback-suppression-sweep-routes" {
        & python scripts/run_real_room_playback_suppression.py sweep-routes
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "real-room-playback-suppression-qualify-device" {
        & python scripts/run_real_room_playback_suppression.py qualify-device
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "real-room-playback-suppression-sweep-devices" {
        & python scripts/run_real_room_playback_suppression.py sweep-devices
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "real-room-playback-suppression-check" {
        & python scripts/run_real_room_playback_suppression.py check
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
    "shell" {
        Invoke-Compose run --rm core bash
    }
    "destroy" {
        Invoke-Compose --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans
    }
    "purge" {
        Invoke-Compose --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans
        Remove-ImageIfPresent $Image
        Remove-ImageIfPresent $AudioEvalImage
        Remove-ImageIfPresent $AudioEvalPyannoteImage
        Remove-ImageIfPresent $AudioEvalSortformerImage
        Remove-ImageIfPresent $AudioEvalWhisperImage
        Remove-ImageIfPresent $AudioEvalSpeechBrainSepformerImage
        Remove-ImageIfPresent $AudioEvalWesepImage
    }
    "audio-eval-build" {
        Invoke-Compose --profile audio-eval build audio-eval
    }
    "audio-eval-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval bash scripts/audio_eval_check.sh
    }
    "audio-eval-real-speech-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/prepare_real_speech_fixture.py check
    }
    "audio-eval-real-speech-chunked-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_chunked_diarization_fixture.py oracle
    }
    "audio-eval-crowd-noise-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/prepare_crowd_noise_fixture.py check
    }
    "audio-eval-translation-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_translation_fixture.py check
    }
    "audio-eval-live-capture-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_live_capture_fixture.py --self-test
    }
    "audio-eval-live-capture-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_live_capture_fixture.py check
    }
    "audio-eval-playback-suppression-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_playback_suppression_fixture.py --self-test
    }
    "audio-eval-playback-suppression-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_playback_suppression_fixture.py check
    }
    "audio-eval-fallback-tts-contract-check" {
        Invoke-Compose --profile audio-eval build audio-eval
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_fallback_tts_fixture.py --self-test
    }
    "audio-eval-fallback-tts-check" {
        Invoke-Compose --profile audio-eval build audio-eval
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_fallback_tts_fixture.py check
    }
    "audio-eval-oracle-tse-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_target_speaker_extraction_fixture.py --self-test
    }
    "audio-eval-oracle-tse-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_target_speaker_extraction_fixture.py check
    }
    "audio-eval-mixture-passthrough-tse-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_target_speaker_extraction_fixture.py --self-test
    }
    "audio-eval-mixture-passthrough-tse-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_target_speaker_extraction_fixture.py passthrough-check
    }
    "audio-eval-enrolled-tse-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_enrolled_tse_fixture.py --self-test
    }
    "audio-eval-enrolled-oracle-tse-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_enrolled_tse_fixture.py oracle-check
    }
    "audio-eval-enrolled-mismatch-tse-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_enrolled_tse_fixture.py mismatch-check
    }
    "audio-eval-shell" {
        Invoke-Compose --profile audio-eval run --rm audio-eval bash
    }
    "audio-eval-purge" {
        Invoke-Compose --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans
        Remove-ImageIfPresent $AudioEvalImage
    }
    "audio-eval-pyannote-build" {
        Invoke-Compose --profile audio-eval-pyannote build audio-eval-pyannote
    }
    "audio-eval-pyannote-check" {
        Invoke-Compose --profile audio-eval-pyannote run --rm audio-eval-pyannote python3 scripts/run_pyannote_diarization_fixture.py --score-warning-only
    }
    "audio-eval-pyannote-real-speech-check" {
        Invoke-Compose --profile audio-eval-pyannote run --rm audio-eval-pyannote python3 scripts/run_pyannote_real_speech_fixture.py --score-warning-only
    }
    "audio-eval-pyannote-real-speech-chunked-check" {
        Invoke-Compose --profile audio-eval-pyannote run --rm audio-eval-pyannote python3 scripts/run_pyannote_chunked_real_speech_fixture.py --score-warning-only
    }
    "audio-eval-pyannote-shell" {
        Invoke-Compose --profile audio-eval-pyannote run --rm audio-eval-pyannote bash
    }
    "audio-eval-pyannote-purge" {
        Invoke-Compose --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans
        Remove-ImageIfPresent $AudioEvalPyannoteImage
    }
    "audio-eval-sortformer-build" {
        Invoke-Compose --profile audio-eval-sortformer build audio-eval-sortformer
    }
    "audio-eval-sortformer-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/run_sortformer_real_speech_fixture.py --self-test
    }
    "audio-eval-sortformer-real-speech-check" {
        Invoke-Compose --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_real_speech_fixture.py --score-warning-only
    }
    "audio-eval-sortformer-real-speech-chunked-check" {
        Invoke-Compose --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_chunked_real_speech_fixture.py --score-warning-only
    }
    "audio-eval-sortformer-online-real-speech-check" {
        Invoke-Compose --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_online_real_speech_fixture.py --score-warning-only
    }
    "audio-eval-sortformer-rolling-real-speech-check" {
        Invoke-Compose --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_rolling_real_speech_fixture.py --score-warning-only
    }
    "audio-eval-sortformer-rolling-fleurs-check" {
        Invoke-Compose --profile audio-eval-sortformer build audio-eval-sortformer
        Invoke-Compose --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_rolling_fleurs_fixture.py --score-warning-only
    }
    "audio-eval-sortformer-shell" {
        Invoke-Compose --profile audio-eval-sortformer run --rm audio-eval-sortformer bash
    }
    "audio-eval-sortformer-purge" {
        Invoke-Compose --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans
        Remove-ImageIfPresent $AudioEvalSortformerImage
    }
    "audio-eval-whisper-build" {
        Invoke-Compose --profile audio-eval-whisper build audio-eval-whisper
    }
    "audio-eval-whisper-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_translation_fixture.py --self-test
    }
    "audio-eval-whisper-translation-check" {
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_translation_fixture.py --score-warning-only
    }
    "audio-eval-whisper-rolling-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_rolling_translation_fixture.py --self-test
    }
    "audio-eval-whisper-rolling-translation-check" {
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_rolling_translation_fixture.py --score-warning-only
    }
    "audio-eval-whisper-oracle-tse-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_tse_translation_fixture.py --self-test
    }
    "audio-eval-whisper-oracle-tse-translation-check" {
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --score-warning-only
    }
    "audio-eval-whisper-mixture-passthrough-tse-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_tse_translation_fixture.py --self-test
    }
    "audio-eval-whisper-mixture-passthrough-tse-translation-check" {
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --tse-mode passthrough --expect-passthrough-warning
    }
    "audio-eval-whisper-causal-tse-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_causal_tse_translation_fixture.py --self-test
    }
    "audio-eval-whisper-speechbrain-sepformer-translation-check" {
        Invoke-Compose --profile audio-eval-speechbrain-sepformer build audio-eval-speechbrain-sepformer
        Invoke-Compose --profile audio-eval-speechbrain-sepformer run --rm audio-eval-speechbrain-sepformer python3 scripts/run_speechbrain_sepformer_tse_fixture.py --score-warning-only
        Invoke-Compose --profile audio-eval-whisper build audio-eval-whisper
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --tse-mode external --tse-predictions artifacts/audio_eval/runs/fleurs-speechbrain-sepformer-whamr-tse/speechbrain_sepformer_tse_predictions.jsonl --run-id whisper-tiny-fleurs-speechbrain-sepformer-tse-translation --adapter-id faster_whisper_tiny_speechbrain_sepformer_tse_translate_v1 --score-warning-only
    }
    "audio-eval-whisper-enrolled-oracle-tse-translation-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/benchmark_enrolled_tse_fixture.py oracle-check
        Invoke-Compose --profile audio-eval-whisper build audio-eval-whisper
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --tse-mode external --tse-predictions artifacts/audio_eval/runs/fleurs-enrolled-oracle-target-speaker-extraction/enrolled_oracle_tse_predictions.jsonl --run-id whisper-tiny-fleurs-enrolled-oracle-tse-translation --adapter-id faster_whisper_tiny_enrolled_oracle_tse_translate_v1 --score-warning-only
    }
    "audio-eval-whisper-wesep-translation-check" {
        Invoke-Compose --profile audio-eval-wesep build audio-eval-wesep
        Invoke-Compose --profile audio-eval-wesep run --rm audio-eval-wesep python3 scripts/run_wesep_enrolled_tse_fixture.py
        Invoke-Compose --profile audio-eval-whisper build audio-eval-whisper
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --tse-mode external --tse-predictions artifacts/audio_eval/runs/fleurs-wesep-enrolled-target-speaker-extraction/wesep_enrolled_tse_predictions.jsonl --run-id whisper-tiny-fleurs-wesep-enrolled-tse-translation --adapter-id faster_whisper_tiny_wesep_enrolled_tse_translate_v1
    }
    "audio-eval-whisper-wesep-causal-translation-check" {
        Invoke-Compose --profile audio-eval-wesep build audio-eval-wesep
        Invoke-Compose --profile audio-eval-wesep run --rm audio-eval-wesep python3 scripts/run_wesep_enrolled_tse_fixture.py
        Invoke-Compose --profile audio-eval-sortformer build audio-eval-sortformer
        Invoke-Compose --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_rolling_fleurs_fixture.py --score-warning-only
        Invoke-Compose --profile audio-eval-whisper build audio-eval-whisper
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_causal_tse_translation_fixture.py
    }
    "audio-eval-whisper-shell" {
        Invoke-Compose --profile audio-eval-whisper run --rm audio-eval-whisper bash
    }
    "audio-eval-whisper-purge" {
        Invoke-Compose --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans
        Remove-ImageIfPresent $AudioEvalWhisperImage
    }
    "audio-eval-speechbrain-sepformer-build" {
        Invoke-Compose --profile audio-eval-speechbrain-sepformer build audio-eval-speechbrain-sepformer
    }
    "audio-eval-speechbrain-sepformer-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/run_speechbrain_sepformer_tse_fixture.py --self-test
    }
    "audio-eval-speechbrain-sepformer-check" {
        Invoke-Compose --profile audio-eval-speechbrain-sepformer run --rm audio-eval-speechbrain-sepformer python3 scripts/run_speechbrain_sepformer_tse_fixture.py --score-warning-only
    }
    "audio-eval-speechbrain-sepformer-shell" {
        Invoke-Compose --profile audio-eval-speechbrain-sepformer run --rm audio-eval-speechbrain-sepformer bash
    }
    "audio-eval-speechbrain-sepformer-purge" {
        Invoke-Compose --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans
        Remove-ImageIfPresent $AudioEvalSpeechBrainSepformerImage
    }
    "audio-eval-wesep-build" {
        Invoke-Compose --profile audio-eval-wesep build audio-eval-wesep
    }
    "audio-eval-wesep-contract-check" {
        Invoke-Compose --profile audio-eval run --rm audio-eval python3 scripts/run_wesep_enrolled_tse_fixture.py --self-test
    }
    "audio-eval-wesep-check" {
        Invoke-Compose --profile audio-eval-wesep build audio-eval-wesep
        Invoke-Compose --profile audio-eval-wesep run --rm audio-eval-wesep python3 scripts/run_wesep_enrolled_tse_fixture.py
    }
    "audio-eval-wesep-shell" {
        Invoke-Compose --profile audio-eval-wesep run --rm audio-eval-wesep bash
    }
    "audio-eval-wesep-purge" {
        Invoke-Compose --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans
        Remove-ImageIfPresent $AudioEvalWesepImage
    }
}
