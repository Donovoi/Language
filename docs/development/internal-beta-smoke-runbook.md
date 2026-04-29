# Internal Beta Smoke Runbook

This runbook documents the **current** smoke-verification path for the first internal beta release candidate.
It is intentionally conservative and only claims what the repository can support today without source edits.

## Supported smoke path

The currently supported and realistic smoke path is:

1. run the gateway locally from a repo checkout or unpacked source bundle
2. verify the gateway health/session/SSE baseline on the host
3. launch the Android release app on an Android emulator
4. trigger the scripted live-ingest demo from the host side
5. confirm the app reflects live lane, caption, mode, reset, and lock updates

This path is the primary target because:

- the Android release build defaults to `http://10.0.2.2:8000`, which matches the Android emulator-to-host path
- the gateway already exposes the required REST, SSE, persistence, and mock-live-ingest behavior
- the current packaged Flutter app does **not** inject bearer tokens, so write-route smoke tests require `LANGUAGE_GATEWAY_AUTH_TOKEN` to stay unset

## What you need

- the candidate source checkout **or** the candidate source bundle unpacked locally
- the candidate Android APK from the workflow run or a local `make flutter-release-android` build
- Python 3.11+
- `make`
- Android emulator plus `adb`

If you are rebuilding locally instead of using the workflow APK, you also need Flutter stable and the Android SDK.

## Important caveats before you start

- Leave `LANGUAGE_GATEWAY_AUTH_TOKEN` unset for the app-driven smoke test.
- If you are using the workflow-produced Android APK with no explicit `FIELD_APP_API_BASE_URL`, use an **Android emulator**, not a physical device.
- For device or hosted-gateway testing, rebuild the artifacts with `FIELD_APP_API_BASE_URL` set in the release workflow dispatch form.
- iOS, macOS, and Windows artifacts are still unsigned/manual-follow-up artifacts; this runbook does not claim they are smoke-verified from this Linux prep pass.

## 1. Prepare the gateway host

From a checkout or unpacked source bundle:

```bash
cd <repository-root>
make smoke-local-demo
```

That should verify:

- `GET /health`
- `GET /v1/session`
- `GET /v1/events/stream?mode=FOCUS&max_events=1`

Then launch the gateway for the interactive smoke pass:

```bash
cd <repository-root>
make gateway-run
```

Keep that terminal running.

## 2. Verify the host-side gateway baseline

From another terminal on the same host, verify the gateway is reachable:

```bash
curl http://127.0.0.1:8000/livez
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/v1/session
```

Expected baseline:

- `/livez` returns `{"status":"alive"}`
- `/readyz` returns `{"status":"ready", ...}`
- `/v1/session` returns a populated `FOCUS` session with `speaker-alice` at the top on a fresh reset path

## 3. Install and launch the Android release app

Install the candidate APK onto an Android emulator:

```bash
adb install -r <path-to>/field_app_flutter-<version>-android-release.apk
```

Then launch the app on the emulator.

Expected initial UI state:

- app title shows `Language Field Console`
- live banner switches to `Live updates connected`
- speaker lanes appear
- the top lane is labeled `Primary translation target`
- non-top lanes are labeled `Queued for translation mix`
- the toolbar exposes reset and refresh actions
- mode chips are visible for `Focus`, `Crowd`, and `Locked`

## 4. Exercise the operator controls from the app

With the app connected:

1. tap the `Crowd` chip and confirm the ordering changes
2. tap the reset button and confirm the deterministic scene returns
3. tap a speaker lock icon and confirm the lock state updates
4. tap the same icon again and confirm unlock succeeds

Expected behavior:

- lane ordering updates without a manual app restart
- the lock icon toggles between open and closed
- status text updates after lock/unlock
- the app remains connected to live updates throughout

## 5. Trigger the live-ingest demo from the host side

The current app does not expose a start-live-ingest control, so trigger it from the host:

```bash
curl -X POST 'http://127.0.0.1:8000/v1/mock/live-ingest?interval_ms=350'
```

While that request runs, watch the emulator UI.

Expected live-demo behavior:

- lane status badges move through `Listening`, `Translating`, and `Ready`
- translated captions appear in the active/top lane
- the source caption appears when it differs from the translated caption
- top-speaker ownership moves between speakers during the scripted briefing scenario
- at least one lock/unlock event becomes visible in the lane state during the scenario

## 6. Optional persistence spot-check

If you want one extra confidence pass, stop and restart the gateway after a lock or ingest update, then refresh the app.

Expected behavior:

- the current session mode and lock state survive restart
- the app reconnects and resumes from the latest snapshot

## 7. Record the candidate result

Capture these details in the internal release note or test handoff:

- candidate version
- commit SHA
- workflow run URL
- artifact names used
- whether `FIELD_APP_API_BASE_URL` was injected
- whether auth was left disabled for the smoke test
- pass/fail notes and any known caveats

## Current non-goals for this smoke pass

This runbook does **not** prove:

- signed mobile or desktop distribution
- physical-device networking by default
- gateway auth-enabled write controls from the packaged app
- iOS/macOS/Windows smoke parity from this Linux environment
- production deployment, secrets, or store submission readiness
