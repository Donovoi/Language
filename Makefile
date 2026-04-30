.PHONY: bootstrap gateway-venv generate-contract-bindings contract-bindings-check smoke-local-demo smoke-integration-demo check rust-check python-check flutter-check gateway-run flutter-run gateway-package flutter-release-android source-bundle

VERSION ?= $(shell awk '/^version:/{split($$2, parts, "[+]"); print parts[1]; exit}' apps/field_app_flutter/pubspec.yaml)
FLUTTER ?= $(HOME)/.local/bin/flutter
FLUTTER_RUN_ARGS ?=
GATEWAY_PYTHON ?= services/gateway/.venv/bin/python
GATEWAY_HOST ?= 127.0.0.1
GATEWAY_PORT ?= 8000
INTEGRATION_SMOKE_PORT ?= 8010

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

check: contract-bindings-check rust-check python-check flutter-check

rust-check:
	cargo fmt --all --check
	cargo clippy --workspace --all-targets --all-features -- -D warnings
	cargo test --workspace

python-check: gateway-venv
	cd services/gateway && .venv/bin/python -m ruff check . && .venv/bin/python -m pytest

flutter-check:
	cd apps/field_app_flutter && $(FLUTTER) create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && $(FLUTTER) pub get && $(FLUTTER) analyze && $(FLUTTER) test

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
