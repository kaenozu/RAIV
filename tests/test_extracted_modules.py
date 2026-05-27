from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QImage

from archive_utils import archive_member_output_path, collect_archive_outputs
from renderer_utils import compose_side_by_side_images, iter_difference_points
from ui_text import translate_binding_text, translate_state_text, translate_ui_text


def test_archive_member_output_path_rejects_traversal(tmp_path: Path) -> None:
    assert archive_member_output_path(tmp_path, "../evil.png") is None


def test_collect_archive_outputs_sorts_and_formats_names(tmp_path: Path) -> None:
    nested = tmp_path / "folder"
    nested.mkdir()
    second = nested / "b.png"
    first = tmp_path / "a.png"
    second.write_text("2", encoding="utf-8")
    first.write_text("1", encoding="utf-8")

    images, names = collect_archive_outputs(tmp_path, lambda path: path.suffix.lower() == ".png")

    assert [path.name for path in images] == ["a.png", "b.png"]
    assert names[images[1]] == "folder/b.png"


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
    assert translate_binding_text("左クリック", "en") == "Left click"
    assert translate_state_text("処理済み", "en") == "Processed"
