from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QImage

from archive_utils import archive_member_output_path, collect_archive_outputs, find_unsafe_archive_members
from renderer_utils import compose_side_by_side_images, iter_difference_points
from ui_text import UI_TEXT_EN, translate_binding_text, translate_state_text, translate_ui_text


def test_archive_member_output_path_rejects_traversal(tmp_path: Path) -> None:
    assert archive_member_output_path(tmp_path, "../evil.png") is None


def test_collect_archive_outputs_sorts_and_formats_names(tmp_path: Path) -> None:
    nested = tmp_path / "folder"
    nested.mkdir()
    second = nested / "10.png"
    first = nested / "1.png"
    middle = nested / "2.png"
    second.write_text("2", encoding="utf-8")
    first.write_text("1", encoding="utf-8")
    middle.write_text("3", encoding="utf-8")

    images, names = collect_archive_outputs(tmp_path, lambda path: path.suffix.lower() == ".png")

    assert [path.name for path in images] == ["1.png", "2.png", "10.png"]
    assert names[images[2]] == "folder/10.png"


def test_find_unsafe_archive_members_detects_traversal_paths() -> None:
    unsafe = find_unsafe_archive_members(["safe/a.png", "../evil.png", "folder/ok.jpg"])
    assert unsafe == ["../evil.png"]


def test_find_unsafe_archive_members_detects_drive_prefix() -> None:
    unsafe = find_unsafe_archive_members(["C:/evil.png", "safe.png"])
    assert unsafe == ["C:/evil.png"]


def test_compose_side_by_side_images_uses_combined_width() -> None:
    left = QImage(2, 1, QImage.Format_ARGB32)
    right = QImage(3, 1, QImage.Format_ARGB32)
    left.fill(QColor("red"))
    right.fill(QColor("blue"))

    composed = compose_side_by_side_images(left, right)

    assert composed.width() == 5
    assert composed.height() == 1


def test_iter_difference_points_reports_changed_pixels() -> None:
    left = QImage(2, 2, QImage.Format_ARGB32)
    right = QImage(2, 2, QImage.Format_ARGB32)
    left.fill(QColor("black"))
    right.fill(QColor("black"))
    right.setPixelColor(1, 1, QColor("white"))

    points = list(iter_difference_points(left, right, threshold=1))

    assert (1, 1) in points


def test_ui_text_helpers_translate_for_english() -> None:
    assert translate_ui_text("画像を開く", "en") == "Open image"
    assert translate_ui_text("エンジン設定", "en") == "Engine settings"
    assert translate_ui_text("Engine settings", "ja") == "エンジン設定"
    assert translate_ui_text("表示言語", "en") == "Language"
    assert translate_ui_text("Language", "ja") == "表示言語"
    assert translate_binding_text("左クリック", "en") == "Left click"
    assert translate_state_text("処理済み", "en") == "Processed"


def test_ui_text_english_values_are_unique() -> None:
    values = list(UI_TEXT_EN.values())
    assert len(values) == len(set(values))
