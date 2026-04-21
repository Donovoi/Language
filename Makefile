.PHONY: bootstrap check rust-check python-check flutter-check gateway-run flutter-run gateway-package flutter-release-android source-bundle

VERSION ?= $(shell awk '/^version:/{split($$2, parts, "+"); print parts[1]; exit}' apps/field_app_flutter/pubspec.yaml)

bootstrap:
	cargo fetch
	cd services/gateway && python -m pip install -e '.[dev]'
	cd apps/field_app_flutter && flutter create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && flutter pub get

check: rust-check python-check flutter-check

rust-check:
	cargo fmt --all --check
	cargo clippy --workspace --all-targets --all-features -- -D warnings
	cargo test --workspace

python-check:
	cd services/gateway && python -m pip install -e '.[dev]' && python -m ruff check . && python -m pytest

flutter-check:
	cd apps/field_app_flutter && flutter create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && flutter pub get && flutter analyze && flutter test

gateway-run:
	cd services/gateway && python -m pip install -e . && uvicorn app.main:app --reload

flutter-run:
	cd apps/field_app_flutter && flutter create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && flutter pub get && flutter run

gateway-package:
	cd services/gateway && python -m pip install build && python -m build

flutter-release-android:
	cd apps/field_app_flutter && flutter create . --platforms=android,ios,macos,windows && rm -f test/widget_test.dart && flutter pub get && flutter build apk --release && flutter build appbundle --release

source-bundle:
	mkdir -p dist && git archive --format=tar.gz --output=dist/language-$(VERSION)-source.tar.gz HEAD && git archive --format=zip --output=dist/language-$(VERSION)-source.zip HEAD
