.PHONY: bootstrap gateway-venv check rust-check python-check flutter-check gateway-run flutter-run gateway-package flutter-release-android source-bundle

VERSION ?= $(shell awk '/^version:/{split($$2, parts, "[+]"); print parts[1]; exit}' apps/field_app_flutter/pubspec.yaml)
FLUTTER ?= $(HOME)/.local/bin/flutter
GATEWAY_PYTHON ?= services/gateway/.venv/bin/python

bootstrap:
	bash scripts/bootstrap_dev.sh

gateway-venv:
	cd services/gateway && python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -e '.[dev]'

check: rust-check python-check flutter-check

rust-check:
	cargo fmt --all --check
	cargo clippy --workspace --all-targets --all-features -- -D warnings
	cargo test --workspace

python-check: gateway-venv
	cd services/gateway && .venv/bin/python -m ruff check . && .venv/bin/python -m pytest

flutter-check:
	cd apps/field_app_flutter && $(FLUTTER) create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && $(FLUTTER) pub get && $(FLUTTER) analyze && $(FLUTTER) test

gateway-run: gateway-venv
	cd services/gateway && .venv/bin/python -m uvicorn app.main:app --reload

flutter-run:
	cd apps/field_app_flutter && $(FLUTTER) create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && $(FLUTTER) pub get && $(FLUTTER) run

gateway-package: gateway-venv
	cd services/gateway && .venv/bin/python -m pip install build && .venv/bin/python -m build

flutter-release-android:
	cd apps/field_app_flutter && $(FLUTTER) create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && $(FLUTTER) pub get && $(FLUTTER) build apk --release && $(FLUTTER) build appbundle --release

source-bundle:
	mkdir -p dist && git archive --format=tar.gz --output=dist/language-$(VERSION)-source.tar.gz HEAD && git archive --format=zip --output=dist/language-$(VERSION)-source.zip HEAD
