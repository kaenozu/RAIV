# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

## [1.0.2] - 2026-06-08

### Added
- PDF page rendering support with progress dialog and cancel support.
- Config regression tests for runtime field normalization and backup recovery.

### Changed
- Refactored config persistence and startup UX with safer corrupt config recovery paths.
- Improved side panel detach/reattach and auto-position behavior with better geometry clamping.
- Refined release automation workflows for packaging and GitHub Releases.
- Migrated config binding helpers to centralized config module and updated import style.

### Fixed
- Hardened config loading against corrupt or missing fields with backup restore on failure.
- Fixed command template error handling to return controlled ValueError for malformed placeholders.
- Fixed side panel interaction behavior after detach/reattach in auto mode.
- Fixed mypy issues in config and event handlers.
- Fixed config type guard for mypy compatibility.

## [1.0.1] - 2026-05-28

### Added
- Settings panel can be detached as a separate window and reopened from the main viewer when hidden.

### Changed
- Settings panel now supports left/right/top/bottom docking with persisted panel width and position.
- Internal maintenance: synced upstream/main history into fork main while preserving RAIV v1 content.

### Fixed
- Hardened engine output handling to avoid leaving incomplete output files after failed processing attempts.

## [0.1.0] - 2026-05-27

### Added
- Initial public release baseline.
