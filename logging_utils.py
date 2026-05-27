from __future__ import annotations

LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARN = "WARN"
LOG_LEVEL_ERROR = "ERROR"

LOG_LEVELS = [LOG_LEVEL_INFO, LOG_LEVEL_WARN, LOG_LEVEL_ERROR]
LOG_LEVEL_RANK = {
    LOG_LEVEL_INFO: 0,
    LOG_LEVEL_WARN: 1,
    LOG_LEVEL_ERROR: 2,
}


def sanitize_log_level(level: str | None) -> str:
    if level in LOG_LEVELS:
        return level
    return LOG_LEVEL_INFO


def can_emit_log(message_level: str, configured_level: str) -> bool:
    current = sanitize_log_level(configured_level)
    return LOG_LEVEL_RANK.get(message_level, 0) >= LOG_LEVEL_RANK.get(current, 0)
