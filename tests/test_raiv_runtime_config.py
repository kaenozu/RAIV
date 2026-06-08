from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QRect

import raiv


def test_raiv_load_config_normalizes_runtime_fields(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "setting.json"
    backup_path = tmp_path / "setting.json.bak"
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

    monkeypatch.setattr(raiv, "APP_DIR", tmp_path)
    monkeypatch.setattr(raiv, "CONFIG_PATH", config_path)
    monkeypatch.setattr(raiv, "CONFIG_BACKUP_PATH", backup_path)

    loaded = raiv.load_config()

    assert loaded.sort_mode == "name"
    assert loaded.thumbnail_worker_count == raiv.MAX_THUMBNAIL_WORKER_COUNT
    assert loaded.recent_dirs == ["A"]
    assert loaded.bookmarks == ["B"]
    assert loaded.favorites == ["C"]
    assert loaded.engine_retry_count == raiv.MAX_ENGINE_RETRY_COUNT
    assert loaded.max_safe_image_pixels == 1_000_000


def test_raiv_load_config_recovers_from_backup(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "setting.json"
    backup_path = tmp_path / "setting.json.bak"
    config_path.write_text("{broken json", encoding="utf-8")
    backup_path.write_text(json.dumps({"sort_mode": "date", "compare_split": 50}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(raiv, "APP_DIR", tmp_path)
    monkeypatch.setattr(raiv, "CONFIG_PATH", config_path)
    monkeypatch.setattr(raiv, "CONFIG_BACKUP_PATH", backup_path)

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
