# Versioning Guidance

This repository uses Semantic Versioning (`MAJOR.MINOR.PATCH`) with git tags formatted as
`vMAJOR.MINOR.PATCH`.

## Release line

- Start the first public release at `0.1.0`.
- Use one repository release version across release notes, tags, and any published package metadata.
- Use bare versions like `0.1.0` in changelog headings, while git tags keep the `v` prefix
  (for example, `## [0.1.0]` in `CHANGELOG.md` and `v0.1.0` for the tag).

## When to increment

- **Major**: incompatible changes to documented external interfaces or release expectations.
- **Minor**: backward-compatible features or meaningful surface-area additions.
- **Patch**: backward-compatible fixes, documentation corrections, or packaging-only adjustments.

## Documentation rules

- Update `CHANGELOG.md` before creating the release tag.
- Make sure the changelog entry and the git tag refer to the same release version, with tags
  formatted as `vMAJOR.MINOR.PATCH`.
- Keep release notes concise and focused on externally visible changes.
