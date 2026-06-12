.PHONY: bootstrap gateway-venv generate-contract-bindings contract-bindings-check research-pack research-pack-check audio-corpus-catalog-check smoke-local-demo smoke-integration-demo check release-audio-gate live-microphone-capture-list-devices live-microphone-capture-check real-room-playback-suppression-list-devices real-room-playback-suppression-contract-check headphone-isolation-contract-check headphone-isolation-list-devices headphone-isolation-capture real-room-playback-suppression-probe-route real-room-playback-suppression-sweep-routes real-room-playback-suppression-qualify-device real-room-playback-suppression-sweep-devices real-room-playback-suppression-check rust-check python-check flutter-check dev-env-build dev-env-check dev-env-shell dev-env-destroy dev-env-purge audio-eval-build audio-eval-check audio-eval-real-speech-check audio-eval-real-speech-chunked-check audio-eval-crowd-noise-check audio-eval-translation-check audio-eval-live-capture-contract-check audio-eval-live-capture-check audio-eval-playback-suppression-contract-check audio-eval-playback-suppression-check audio-eval-fallback-tts-contract-check audio-eval-fallback-tts-check audio-eval-oracle-tse-contract-check audio-eval-oracle-tse-check audio-eval-mixture-passthrough-tse-contract-check audio-eval-mixture-passthrough-tse-check audio-eval-enrolled-tse-contract-check audio-eval-enrolled-oracle-tse-check audio-eval-enrolled-mismatch-tse-check audio-eval-shell audio-eval-purge audio-eval-pyannote-build audio-eval-pyannote-check audio-eval-pyannote-real-speech-check audio-eval-pyannote-real-speech-chunked-check audio-eval-pyannote-shell audio-eval-pyannote-purge audio-eval-sortformer-build audio-eval-sortformer-contract-check audio-eval-sortformer-real-speech-check audio-eval-sortformer-real-speech-chunked-check audio-eval-sortformer-online-real-speech-check audio-eval-sortformer-rolling-real-speech-check audio-eval-sortformer-rolling-fleurs-check audio-eval-sortformer-shell audio-eval-sortformer-purge audio-eval-whisper-build audio-eval-whisper-contract-check audio-eval-whisper-translation-check audio-eval-whisper-rolling-contract-check audio-eval-whisper-rolling-translation-check audio-eval-whisper-oracle-tse-contract-check audio-eval-whisper-oracle-tse-translation-check audio-eval-whisper-mixture-passthrough-tse-contract-check audio-eval-whisper-mixture-passthrough-tse-translation-check audio-eval-whisper-causal-tse-contract-check audio-eval-whisper-speechbrain-sepformer-translation-check audio-eval-whisper-enrolled-oracle-tse-translation-check audio-eval-whisper-wesep-translation-check audio-eval-whisper-wesep-causal-translation-check audio-eval-whisper-shell audio-eval-whisper-purge audio-eval-speechbrain-sepformer-build audio-eval-speechbrain-sepformer-contract-check audio-eval-speechbrain-sepformer-check audio-eval-speechbrain-sepformer-shell audio-eval-speechbrain-sepformer-purge audio-eval-wesep-build audio-eval-wesep-contract-check audio-eval-wesep-check audio-eval-wesep-shell audio-eval-wesep-purge gateway-run flutter-run gateway-package flutter-release-android source-bundle

VERSION ?= $(shell awk '/^version:/{split($$2, parts, "[+]"); print parts[1]; exit}' apps/field_app_flutter/pubspec.yaml)
FLUTTER ?= $(HOME)/.local/bin/flutter
FLUTTER_RUN_ARGS ?=
GATEWAY_PYTHON ?= services/gateway/.venv/bin/python
GATEWAY_HOST ?= 127.0.0.1
GATEWAY_PORT ?= 8000
INTEGRATION_SMOKE_PORT ?= 8010
DOCKER_COMPOSE ?= docker compose
DOCKER ?= docker
DEV_COMPOSE_FILE ?= docker/dev/compose.yml
DEV_IMAGE ?= language-core-dev:local
AUDIO_EVAL_IMAGE ?= language-audio-eval-dev:local
AUDIO_EVAL_PYANNOTE_IMAGE ?= language-audio-eval-pyannote-dev:local
AUDIO_EVAL_SORTFORMER_IMAGE ?= language-audio-eval-sortformer-dev:local
AUDIO_EVAL_WHISPER_IMAGE ?= language-audio-eval-whisper-dev:local
AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE ?= language-audio-eval-speechbrain-sepformer-dev:local
AUDIO_EVAL_WESEP_IMAGE ?= language-audio-eval-wesep-dev:local
HEADPHONE_ISOLATION_CAPTURE_ARGS ?=

bootstrap:
	bash scripts/bootstrap_dev.sh

generate-contract-bindings:
	python3 scripts/generate_contract_bindings.py

contract-bindings-check:
	python3 scripts/generate_contract_bindings.py --check

gateway-venv:
	cd services/gateway && python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -e '.[dev]'

smoke-local-demo:
	GATEWAY_HOST=$(GATEWAY_HOST) GATEWAY_PORT=$(GATEWAY_PORT) GATEWAY_PYTHON=$(abspath $(GATEWAY_PYTHON)) bash scripts/smoke_local_demo.sh

smoke-integration-demo: gateway-venv
	GATEWAY_HOST=$(GATEWAY_HOST) GATEWAY_PORT=$(INTEGRATION_SMOKE_PORT) GATEWAY_PYTHON=$(abspath $(GATEWAY_PYTHON)) bash scripts/smoke_integration_demo.sh

check: contract-bindings-check research-pack-check audio-corpus-catalog-check rust-check python-check flutter-check

release-audio-gate:
	python3 scripts/release_audio_gate.py

live-microphone-capture-list-devices:
	python3 scripts/run_live_microphone_capture.py list-devices

live-microphone-capture-check:
	python3 scripts/run_live_microphone_capture.py check

real-room-playback-suppression-list-devices:
	python3 scripts/run_real_room_playback_suppression.py list-devices

real-room-playback-suppression-contract-check:
	python3 scripts/run_real_room_playback_suppression.py self-test

headphone-isolation-contract-check:
	python3 scripts/run_headphone_isolation_check.py self-test

headphone-isolation-list-devices:
	python3 scripts/run_headphone_isolation_check.py list-devices

headphone-isolation-capture:
	python3 scripts/run_headphone_isolation_check.py capture $(HEADPHONE_ISOLATION_CAPTURE_ARGS)

real-room-playback-suppression-probe-route:
	python3 scripts/run_real_room_playback_suppression.py probe-route

real-room-playback-suppression-sweep-routes:
	python3 scripts/run_real_room_playback_suppression.py sweep-routes

real-room-playback-suppression-qualify-device:
	python3 scripts/run_real_room_playback_suppression.py qualify-device

real-room-playback-suppression-sweep-devices:
	python3 scripts/run_real_room_playback_suppression.py sweep-devices

real-room-playback-suppression-check:
	python3 scripts/run_real_room_playback_suppression.py check

research-pack:
	python3 scripts/prepare_robin_research_pack.py

research-pack-check:
	python3 scripts/prepare_robin_research_pack.py --check

audio-corpus-catalog-check:
	python3 scripts/check_audio_corpus_catalog.py

rust-check:
	cargo fmt --all --check
	cargo clippy --workspace --all-targets --all-features -- -D warnings
	cargo test --workspace

python-check: gateway-venv
	cd services/gateway && .venv/bin/python -m ruff check . && .venv/bin/python -m pytest

flutter-check:
	cd apps/field_app_flutter && $(FLUTTER) create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && $(FLUTTER) pub get && $(FLUTTER) analyze && $(FLUTTER) test

dev-env-build:
	DEV_IMAGE=$(DEV_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) build core

dev-env-check:
	DEV_IMAGE=$(DEV_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) run --rm core bash scripts/dev_container_check.sh

dev-env-shell:
	DEV_IMAGE=$(DEV_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) run --rm core bash

dev-env-destroy:
	DEV_IMAGE=$(DEV_IMAGE) AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) AUDIO_EVAL_PYANNOTE_IMAGE=$(AUDIO_EVAL_PYANNOTE_IMAGE) AUDIO_EVAL_SORTFORMER_IMAGE=$(AUDIO_EVAL_SORTFORMER_IMAGE) AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE=$(AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE) AUDIO_EVAL_WESEP_IMAGE=$(AUDIO_EVAL_WESEP_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval --profile audio-eval-pyannote --profile audio-eval-sortformer --profile audio-eval-whisper --profile audio-eval-speechbrain-sepformer --profile audio-eval-wesep down --volumes --remove-orphans

dev-env-purge: dev-env-destroy
	-$(DOCKER) image rm $(DEV_IMAGE)
	-$(DOCKER) image rm $(AUDIO_EVAL_IMAGE)
	-$(DOCKER) image rm $(AUDIO_EVAL_PYANNOTE_IMAGE)
	-$(DOCKER) image rm $(AUDIO_EVAL_SORTFORMER_IMAGE)
	-$(DOCKER) image rm $(AUDIO_EVAL_WHISPER_IMAGE)
	-$(DOCKER) image rm $(AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE)
	-$(DOCKER) image rm $(AUDIO_EVAL_WESEP_IMAGE)

audio-eval-build:
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval build audio-eval

audio-eval-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval bash scripts/audio_eval_check.sh

audio-eval-real-speech-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/prepare_real_speech_fixture.py check

audio-eval-real-speech-chunked-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_chunked_diarization_fixture.py oracle

audio-eval-crowd-noise-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/prepare_crowd_noise_fixture.py check

audio-eval-translation-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_translation_fixture.py check

audio-eval-live-capture-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_live_capture_fixture.py --self-test

audio-eval-live-capture-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_live_capture_fixture.py check

audio-eval-playback-suppression-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_playback_suppression_fixture.py --self-test

audio-eval-playback-suppression-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_playback_suppression_fixture.py check

audio-eval-fallback-tts-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_fallback_tts_fixture.py --self-test

audio-eval-fallback-tts-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_fallback_tts_fixture.py check

audio-eval-oracle-tse-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_target_speaker_extraction_fixture.py --self-test

audio-eval-oracle-tse-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_target_speaker_extraction_fixture.py check

audio-eval-mixture-passthrough-tse-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_target_speaker_extraction_fixture.py --self-test

audio-eval-mixture-passthrough-tse-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_target_speaker_extraction_fixture.py passthrough-check

audio-eval-enrolled-tse-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_enrolled_tse_fixture.py --self-test

audio-eval-enrolled-oracle-tse-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_enrolled_tse_fixture.py oracle-check

audio-eval-enrolled-mismatch-tse-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/benchmark_enrolled_tse_fixture.py mismatch-check

audio-eval-shell:
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval bash

audio-eval-purge: dev-env-destroy
	-$(DOCKER) image rm $(AUDIO_EVAL_IMAGE)

audio-eval-pyannote-build:
	AUDIO_EVAL_PYANNOTE_IMAGE=$(AUDIO_EVAL_PYANNOTE_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-pyannote build audio-eval-pyannote

audio-eval-pyannote-check: audio-eval-pyannote-build
	AUDIO_EVAL_PYANNOTE_IMAGE=$(AUDIO_EVAL_PYANNOTE_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-pyannote run --rm audio-eval-pyannote python3 scripts/run_pyannote_diarization_fixture.py --score-warning-only

audio-eval-pyannote-real-speech-check: audio-eval-pyannote-build
	AUDIO_EVAL_PYANNOTE_IMAGE=$(AUDIO_EVAL_PYANNOTE_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-pyannote run --rm audio-eval-pyannote python3 scripts/run_pyannote_real_speech_fixture.py --score-warning-only

audio-eval-pyannote-real-speech-chunked-check: audio-eval-pyannote-build
	AUDIO_EVAL_PYANNOTE_IMAGE=$(AUDIO_EVAL_PYANNOTE_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-pyannote run --rm audio-eval-pyannote python3 scripts/run_pyannote_chunked_real_speech_fixture.py --score-warning-only

audio-eval-pyannote-shell:
	AUDIO_EVAL_PYANNOTE_IMAGE=$(AUDIO_EVAL_PYANNOTE_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-pyannote run --rm audio-eval-pyannote bash

audio-eval-pyannote-purge: dev-env-destroy
	-$(DOCKER) image rm $(AUDIO_EVAL_PYANNOTE_IMAGE)

audio-eval-sortformer-build:
	AUDIO_EVAL_SORTFORMER_IMAGE=$(AUDIO_EVAL_SORTFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-sortformer build audio-eval-sortformer

audio-eval-sortformer-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/run_sortformer_real_speech_fixture.py --self-test

audio-eval-sortformer-real-speech-check: audio-eval-sortformer-build
	AUDIO_EVAL_SORTFORMER_IMAGE=$(AUDIO_EVAL_SORTFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_real_speech_fixture.py --score-warning-only

audio-eval-sortformer-real-speech-chunked-check: audio-eval-sortformer-build
	AUDIO_EVAL_SORTFORMER_IMAGE=$(AUDIO_EVAL_SORTFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_chunked_real_speech_fixture.py --score-warning-only

audio-eval-sortformer-online-real-speech-check: audio-eval-sortformer-build
	AUDIO_EVAL_SORTFORMER_IMAGE=$(AUDIO_EVAL_SORTFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_online_real_speech_fixture.py --score-warning-only

audio-eval-sortformer-rolling-real-speech-check: audio-eval-sortformer-build
	AUDIO_EVAL_SORTFORMER_IMAGE=$(AUDIO_EVAL_SORTFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_rolling_real_speech_fixture.py --score-warning-only

audio-eval-sortformer-rolling-fleurs-check: audio-eval-sortformer-build
	AUDIO_EVAL_SORTFORMER_IMAGE=$(AUDIO_EVAL_SORTFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-sortformer run --rm audio-eval-sortformer python3 scripts/run_sortformer_rolling_fleurs_fixture.py --score-warning-only

audio-eval-sortformer-shell:
	AUDIO_EVAL_SORTFORMER_IMAGE=$(AUDIO_EVAL_SORTFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-sortformer run --rm audio-eval-sortformer bash

audio-eval-sortformer-purge: dev-env-destroy
	-$(DOCKER) image rm $(AUDIO_EVAL_SORTFORMER_IMAGE)

audio-eval-whisper-build:
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper build audio-eval-whisper

audio-eval-whisper-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_translation_fixture.py --self-test

audio-eval-whisper-translation-check: audio-eval-whisper-build
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_translation_fixture.py --score-warning-only

audio-eval-whisper-rolling-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_rolling_translation_fixture.py --self-test

audio-eval-whisper-rolling-translation-check: audio-eval-whisper-build
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_rolling_translation_fixture.py --score-warning-only

audio-eval-whisper-oracle-tse-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_tse_translation_fixture.py --self-test

audio-eval-whisper-oracle-tse-translation-check: audio-eval-whisper-build
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --score-warning-only

audio-eval-whisper-mixture-passthrough-tse-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_tse_translation_fixture.py --self-test

audio-eval-whisper-mixture-passthrough-tse-translation-check: audio-eval-whisper-build
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --tse-mode passthrough --expect-passthrough-warning

audio-eval-whisper-causal-tse-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/run_whisper_causal_tse_translation_fixture.py --self-test

audio-eval-whisper-speechbrain-sepformer-translation-check: audio-eval-whisper-build audio-eval-speechbrain-sepformer-check
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --tse-mode external --tse-predictions artifacts/audio_eval/runs/fleurs-speechbrain-sepformer-whamr-tse/speechbrain_sepformer_tse_predictions.jsonl --run-id whisper-tiny-fleurs-speechbrain-sepformer-tse-translation --adapter-id faster_whisper_tiny_speechbrain_sepformer_tse_translate_v1 --score-warning-only

audio-eval-whisper-enrolled-oracle-tse-translation-check: audio-eval-whisper-build audio-eval-enrolled-oracle-tse-check
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --tse-mode external --tse-predictions artifacts/audio_eval/runs/fleurs-enrolled-oracle-target-speaker-extraction/enrolled_oracle_tse_predictions.jsonl --run-id whisper-tiny-fleurs-enrolled-oracle-tse-translation --adapter-id faster_whisper_tiny_enrolled_oracle_tse_translate_v1 --score-warning-only

audio-eval-whisper-wesep-translation-check: audio-eval-whisper-build audio-eval-wesep-check
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_tse_translation_fixture.py --tse-mode external --tse-predictions artifacts/audio_eval/runs/fleurs-wesep-enrolled-target-speaker-extraction/wesep_enrolled_tse_predictions.jsonl --run-id whisper-tiny-fleurs-wesep-enrolled-tse-translation --adapter-id faster_whisper_tiny_wesep_enrolled_tse_translate_v1

audio-eval-whisper-wesep-causal-translation-check: audio-eval-whisper-build audio-eval-wesep-check audio-eval-sortformer-rolling-fleurs-check
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper python3 scripts/run_whisper_causal_tse_translation_fixture.py

audio-eval-whisper-shell:
	AUDIO_EVAL_WHISPER_IMAGE=$(AUDIO_EVAL_WHISPER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-whisper run --rm audio-eval-whisper bash

audio-eval-whisper-purge: dev-env-destroy
	-$(DOCKER) image rm $(AUDIO_EVAL_WHISPER_IMAGE)

audio-eval-speechbrain-sepformer-build:
	AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE=$(AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-speechbrain-sepformer build audio-eval-speechbrain-sepformer

audio-eval-speechbrain-sepformer-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/run_speechbrain_sepformer_tse_fixture.py --self-test

audio-eval-speechbrain-sepformer-check: audio-eval-speechbrain-sepformer-build
	AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE=$(AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-speechbrain-sepformer run --rm audio-eval-speechbrain-sepformer python3 scripts/run_speechbrain_sepformer_tse_fixture.py --score-warning-only

audio-eval-speechbrain-sepformer-shell:
	AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE=$(AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-speechbrain-sepformer run --rm audio-eval-speechbrain-sepformer bash

audio-eval-speechbrain-sepformer-purge: dev-env-destroy
	-$(DOCKER) image rm $(AUDIO_EVAL_SPEECHBRAIN_SEPFORMER_IMAGE)

audio-eval-wesep-build:
	AUDIO_EVAL_WESEP_IMAGE=$(AUDIO_EVAL_WESEP_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-wesep build audio-eval-wesep

audio-eval-wesep-contract-check: audio-eval-build
	AUDIO_EVAL_IMAGE=$(AUDIO_EVAL_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval run --rm audio-eval python3 scripts/run_wesep_enrolled_tse_fixture.py --self-test

audio-eval-wesep-check: audio-eval-wesep-build
	AUDIO_EVAL_WESEP_IMAGE=$(AUDIO_EVAL_WESEP_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-wesep run --rm audio-eval-wesep python3 scripts/run_wesep_enrolled_tse_fixture.py

audio-eval-wesep-shell:
	AUDIO_EVAL_WESEP_IMAGE=$(AUDIO_EVAL_WESEP_IMAGE) $(DOCKER_COMPOSE) -f $(DEV_COMPOSE_FILE) --profile audio-eval-wesep run --rm audio-eval-wesep bash

audio-eval-wesep-purge: dev-env-destroy
	-$(DOCKER) image rm $(AUDIO_EVAL_WESEP_IMAGE)

gateway-run: gateway-venv
	cd services/gateway && .venv/bin/python -m uvicorn app.main:app --host $(GATEWAY_HOST) --port $(GATEWAY_PORT) --reload

flutter-run:
	cd apps/field_app_flutter && $(FLUTTER) create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && $(FLUTTER) pub get && $(FLUTTER) run $(FLUTTER_RUN_ARGS)

gateway-package: gateway-venv
	cd services/gateway && .venv/bin/python -m pip install build && .venv/bin/python -m build

flutter-release-android:
	cd apps/field_app_flutter && $(FLUTTER) create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && $(FLUTTER) pub get && $(FLUTTER) build apk --release && $(FLUTTER) build appbundle --release

source-bundle:
	mkdir -p dist && git archive --format=tar.gz --output=dist/language-$(VERSION)-source.tar.gz HEAD && git archive --format=zip --output=dist/language-$(VERSION)-source.zip HEAD
