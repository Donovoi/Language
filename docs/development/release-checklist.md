# Release Checklist

Use this checklist when preparing a repository release.

## Before tagging

1. Confirm the release scope and target version.
2. Update `CHANGELOG.md` with the release summary.
3. Make sure version strings and release notes match the guidance in `versioning.md`.
4. Run the repository's existing validation commands on a clean branch.

## Cut the release

1. Create an annotated git tag named `vX.Y.Z`.
2. Publish release notes from the matching `CHANGELOG.md` entry.
3. Point consumers to any docs that changed with the release.

## After release

1. Add or refresh the next changelog entry when new work starts.
2. Capture any release follow-ups before the next version is planned.
