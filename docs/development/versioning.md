# Versioning Guidance

This repository uses Semantic Versioning (`MAJOR.MINOR.PATCH`) with git tags formatted as `vMAJOR.MINOR.PATCH`.

## Release line

- Start the first public release at `0.1.0`.
- Use one repository release version across release notes, tags, and any published package metadata.

## When to increment

- **Major**: incompatible changes to documented external interfaces or release expectations.
- **Minor**: backward-compatible features or meaningful surface-area additions.
- **Patch**: backward-compatible fixes, documentation corrections, or packaging-only adjustments.

## Documentation rules

- Update `CHANGELOG.md` before creating the release tag.
- Use the exact same version string in the changelog entry and the git tag.
- Keep release notes concise and focused on externally visible changes.
