from __future__ import annotations

import json
import os
from typing import Any

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

import config as config_module
import raiv


def _patch_config_paths(monkeypatch, tmp_path) -> None:
    """Monkeypatch config module path constants since load_config lives in config."""
    config_path = tmp_path / "setting.json"
    backup_path = tmp_path / "setting.json.bak"
    monkeypatch.setattr(config_module, "APP_DIR", tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_module, "CONFIG_BACKUP_PATH", backup_path)
    return config_path, backup_path


def test_raiv_load_config_normalizes_runtime_fields(tmp_path, monkeypatch) -> None:
    config_path, _backup_path = _patch_config_paths(monkeypatch, tmp_path)
    config_path.write_text(
        json.dumps(
            {
                "sort_mode": "invalid",
                "thumbnail_worker_count": 999,
                "recent_dirs": ["A", "", 1],
                "bookmarks": ["B", "", 2],
                "favorites": ["C", "", 3],
                "engine_retry_count": 999,
                "max_safe_image_pixels": 1,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    loaded = raiv.load_config()

    assert loaded.sort_mode == "name"
    assert loaded.thumbnail_worker_count == raiv.MAX_THUMBNAIL_WORKER_COUNT
    assert loaded.recent_dirs == ["A"]
    assert loaded.bookmarks == ["B"]
    assert loaded.favorites == ["C"]
    assert loaded.engine_retry_count == raiv.MAX_ENGINE_RETRY_COUNT
    assert loaded.max_safe_image_pixels == 1_000_000


def test_raiv_load_config_recovers_from_backup(tmp_path, monkeypatch) -> None:
    config_path, backup_path = _patch_config_paths(monkeypatch, tmp_path)
    config_path.write_text("{broken json", encoding="utf-8")
    backup_path.write_text(json.dumps({"sort_mode": "date", "compare_split": 50}, ensure_ascii=False), encoding="utf-8")

    loaded = raiv.load_config()

    assert loaded.sort_mode == "date"
    assert loaded.compare_split == 500
    assert json.loads(config_path.read_text(encoding="utf-8"))["sort_mode"] == "date"


def test_side_panel_window_rect_is_clamped_to_available_geometry() -> None:
    class DummyWindow:
        _clamp_rect_to_available_geometry = raiv.MainWindow._clamp_rect_to_available_geometry

        def _available_virtual_geometry(self) -> QRect:
            return QRect(0, 0, 1920, 1080)

    dummy_window: Any = DummyWindow()
    restored = raiv.MainWindow._restore_side_panel_window_rect(
        dummy_window,
        [-100, -50, 5000, 4000],
    )

    assert restored == (0, 0, 1920, 1080)


def _write_two_page_pdf(path) -> None:
    objects = []
    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>\nendobj\n")
    objects.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 7 0 R >> >> >>\nendobj\n"
    )
    stream1 = b"BT /F1 24 Tf 20 100 Td (Hello PDF 1) Tj ET"
    objects.append(b"4 0 obj\n<< /Length %d >>\nstream\n" % len(stream1) + stream1 + b"\nendstream\nendobj\n")
    objects.append(
        b"5 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 6 0 R /Resources << /Font << /F1 7 0 R >> >> >>\nendobj\n"
    )
    stream2 = b"BT /F1 24 Tf 20 100 Td (Hello PDF 2) Tj ET"
    objects.append(b"6 0 obj\n<< /Length %d >>\nstream\n" % len(stream2) + stream2 + b"\nendstream\nendobj\n")
    objects.append(b"7 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_start = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(b"trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n")
    out.extend(str(xref_start).encode("ascii") + b"\n%%EOF\n")
    path.write_bytes(out)


def test_open_pdf_expands_pages_into_temp_images(tmp_path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pdf_path = tmp_path / "sample.pdf"
    _write_two_page_pdf(pdf_path)

    app = QApplication.instance() or QApplication([])
    window = raiv.MainWindow()
    try:
        window.open_path(pdf_path)
        app.processEvents()

        assert len(window.image_paths) == 2
        assert window.archive_mode_active() is True
        assert window.archive_source_path == pdf_path.resolve()
        assert [window.display_name(path) for path in window.image_paths] == [
            "sample.pdf [page 1]",
            "sample.pdf [page 2]",
        ]
        assert all(path.suffix.lower() == ".png" for path in window.image_paths)
    finally:
        window.close()
        app.processEvents()
