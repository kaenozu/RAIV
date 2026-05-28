from __future__ import annotations

import time
from pathlib import Path

from helpers import (
    archive_display_name,
    cleanup_stale_temp_entries,
    safe_archive_member_parts,
    sort_images,
    sort_images_by_name_casefold,
    split_command_line,
)


def test_sort_images_by_name_casefold_orders_case_insensitive() -> None:
    paths = [Path("b.PNG"), Path("A.jpg"), Path("c.webp")]
    sorted_paths = sort_images_by_name_casefold(paths)
    assert [path.name for path in sorted_paths] == ["A.jpg", "b.PNG", "c.webp"]


def test_sort_images_name_mode_orders_numeric_suffixes() -> None:
    paths = [Path("img10.png"), Path("img2.png"), Path("img1.png")]
    sorted_paths = sort_images(paths, mode="name")
    assert [path.name for path in sorted_paths] == ["img1.png", "img2.png", "img10.png"]


def test_sort_images_natural_mode_orders_numeric_suffixes() -> None:
    paths = [Path("img10.png"), Path("img2.png"), Path("img1.png")]
    sorted_paths = sort_images(paths, mode="natural")
    assert [path.name for path in sorted_paths] == ["img1.png", "img2.png", "img10.png"]


def test_sort_images_date_mode_uses_mtime(tmp_path: Path) -> None:
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.write_text("1", encoding="utf-8")
    time.sleep(0.01)
    second.write_text("2", encoding="utf-8")
    sorted_paths = sort_images([second, first], mode="date")
    assert [path.name for path in sorted_paths] == ["a.png", "b.png"]


def test_cleanup_stale_temp_entries_removes_target_entries(tmp_path: Path) -> None:
    archive_dir = tmp_path / "realcugan_qt_archive_123"
    work_dir = tmp_path / "realcugan_qt_work_123"
    output_png = tmp_path / "realcugan_test.png"
    keep_file = tmp_path / "keep.txt"

    archive_dir.mkdir()
    work_dir.mkdir()
    output_png.write_text("x", encoding="utf-8")
    keep_file.write_text("keep", encoding="utf-8")

    removed_count, errors = cleanup_stale_temp_entries(
        tmp_path,
        "realcugan_qt_archive_",
        "realcugan_qt_work_",
        "realcugan_",
    )

    assert removed_count == 3
    assert not errors
    assert not archive_dir.exists()
    assert not work_dir.exists()
    assert not output_png.exists()
    assert keep_file.exists()


def test_archive_display_name_normalizes_separators() -> None:
    assert archive_display_name("foo\\bar\\img.png") == "foo/bar/img.png"
    assert archive_display_name("/root/img.png") == "root/img.png"


def test_safe_archive_member_parts_rejects_traversal() -> None:
    assert safe_archive_member_parts("../evil.png") is None
    assert safe_archive_member_parts("C:/evil.png") is None


def test_safe_archive_member_parts_sanitizes_reserved_chars() -> None:
    parts = safe_archive_member_parts("folder/te<st>.png")
    assert parts == ("folder", "te_st_.png")


def test_split_command_line_keeps_quoted_paths() -> None:
    command = '"C:/Program Files/tool.exe" -i "C:/work/a b.png" -o "C:/work/out.png"'
    parts = split_command_line(command)
    assert parts[0] == "C:/Program Files/tool.exe"
    assert parts[2] == "C:/work/a b.png"


def test_split_command_line_raises_for_broken_quote() -> None:
    try:
        split_command_line('"C:/broken.exe -i input.png')
    except ValueError:
        return
    raise AssertionError("Expected ValueError for malformed command line")
