.PHONY: bootstrap check rust-check python-check flutter-check gateway-run flutter-run

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
