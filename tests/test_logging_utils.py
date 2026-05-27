from __future__ import annotations

from logging_utils import (
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_WARN,
    can_emit_log,
    sanitize_log_level,
)


def test_sanitize_log_level_defaults_to_info() -> None:
    assert sanitize_log_level("UNKNOWN") == LOG_LEVEL_INFO


def test_sanitize_log_level_keeps_valid_values() -> None:
    assert sanitize_log_level(LOG_LEVEL_WARN) == LOG_LEVEL_WARN


def test_can_emit_log_respects_rank() -> None:
    assert can_emit_log(LOG_LEVEL_ERROR, LOG_LEVEL_WARN) is True
    assert can_emit_log(LOG_LEVEL_INFO, LOG_LEVEL_WARN) is False
