.PHONY: bootstrap check rust-check python-check flutter-check gateway-run flutter-run

bootstrap:
python -m pip install --upgrade pip
python -m pip install -r services/gateway/requirements-dev.txt
cargo fetch
cd apps/field_app_flutter && flutter create . --platforms=android,ios,macos,windows && flutter pub get

check: rust-check python-check flutter-check

rust-check:
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
cargo test --workspace

python-check:
python -m pip install -r services/gateway/requirements-dev.txt
cd services/gateway && ruff check . && pytest

flutter-check:
cd apps/field_app_flutter && flutter create . --platforms=android,ios,macos,windows && flutter pub get && flutter analyze && flutter test

gateway-run:
python -m pip install -r services/gateway/requirements-dev.txt
cd services/gateway && uvicorn app.main:app --reload

flutter-run:
cd apps/field_app_flutter && flutter create . --platforms=android,ios,macos,windows && flutter pub get && flutter run
