.PHONY: bootstrap check fmt lint test

bootstrap:
	@echo "Bootstrap placeholders: install Flutter, Rust, and Python tooling"

check: fmt lint test

fmt:
	@echo "Run formatter placeholders for Dart, Rust, and Python"

lint:
	@echo "Run lint placeholders for Dart, Rust, and Python"

test:
	@echo "Run placeholder tests for shared crates and services"
