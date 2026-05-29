from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path, PurePosixPath
from typing import Mapping


def cleanup_stale_temp_entries(
    temp_root: Path,
    archive_prefix: str,
    work_prefix: str,
    output_prefix: str,
) -> tuple[int, list[str]]:
    removed_count = 0
    errors: list[str] = []
    for entry in list(temp_root.iterdir()):
        try:
            if entry.is_dir() and entry.name.startswith((archive_prefix, work_prefix)):
                shutil.rmtree(entry)
                removed_count += 1
            elif entry.is_file() and entry.name.startswith(output_prefix) and entry.suffix.lower() == ".png":
                entry.unlink(missing_ok=True)
                removed_count += 1
        except OSError as exc:
            errors.append(f"Temp cleanup failed: {entry.name} ({exc})")
    return removed_count, errors


def split_command_line(command: str) -> list[str]:
    parts = [part for part in shlex.split(command, posix=False) if part]
    normalized: list[str] = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {'"', "'"}:
            normalized.append(part[1:-1])
        else:
            normalized.append(part)
    return normalized


def format_command_template(command_template: str, values: Mapping[str, object]) -> str:
    try:
        return command_template.format(**values)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def sort_images(paths: list[Path], mode: str = "name") -> list[Path]:
    if mode == "date":
        return sorted(paths, key=lambda path: path.stat().st_mtime if path.exists() else 0.0)
    return sorted(paths, key=lambda path: natural_sort_key(path.name))


def natural_sort_key(text: str) -> tuple[tuple[int, int | str], ...]:
    key: list[tuple[int, int | str]] = []
    for part in re.split(r"(\d+)", text.casefold()):
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def sort_images_by_name_casefold(paths: list[Path]) -> list[Path]:
    return sort_images(paths, mode="name")


def archive_display_name(member_name: str) -> str:
    return member_name.replace("\\", "/").lstrip("/")


def safe_archive_member_parts(member_name: str) -> tuple[str, ...] | None:
    parts = PurePosixPath(archive_display_name(member_name)).parts
    safe: list[str] = []
    for part in parts:
        if part in {"", ".", "/"}:
            continue
        if part == ".." or ":" in part:
            return None
        safe.append(re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", part))
    return tuple(safe) if safe else None
