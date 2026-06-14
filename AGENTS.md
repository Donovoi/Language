# Agent Instructions

## Disposable Environments

For any change that needs a new runtime, provider, service, model, SDK, system package, or external
tool, add or update disposable test scaffolding in the same change.

Use the existing pattern:

- Docker/Compose files live under `docker/dev/`.
- Verification scripts live under `scripts/`.
- Make targets expose build/run/check/destroy commands.
- Documentation lives in `docs/development/disposable-test-environments.md`.

Before handing off a non-trivial code change, run the smallest relevant disposable check. If a check
cannot run in the current environment, say exactly which target failed and why.

## Token Budget

Keep agent runs token-light by default.

- Prefer `python scripts/run_test_category.py <category>` for long validation; the runner writes full
  logs to `artifacts/test-categories/` by default.
- Use `--dry-run` before unfamiliar categories and `--continue-on-failure` for broad sweeps.
- Reference full logs and JSON reports by path under `artifacts/` instead of pasting them into chat.
- Use targeted searches, JSON projections, and bounded tails instead of dumping whole files.
- Keep the README concise; move command matrices and lab runbooks into `docs/`.
- Treat Headroom or similar compression tools as optional infrastructure until they are pinned and
  evaluated in a disposable environment.

## Research-Gated Audio Decisions

For live audio capture, diarization, separation, language ID, speech translation, voice clone/TTS,
playback mixing, source-voice suppression, model/provider selection, or benchmark design, use the
Robin research gate before implementation.

- Generate or validate the pack with `python scripts/prepare_robin_research_pack.py --check`.
- Use `research/language_stack_questions.json` as the subsystem question matrix.
- Save decision records from `docs/research/decision-record-template.md`.
- Run the detractor loop and record the strongest objection before recommending implementation.
- Prefer peer-reviewed papers and official benchmark/model documentation; label preprints and vendor
  claims when they are used.
- Pair every runtime integration with a disposable benchmark or smoke check.
