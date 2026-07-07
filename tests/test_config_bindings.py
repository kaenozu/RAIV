from __future__ import annotations

import json

from PySide6.QtCore import Qt

import config
from config import (
    IMAGE_EXTENSIONS,
    MODIFIER_MASK,
    default_key_bindings,
    duplicate_binding_signatures,
    key_binding,
    mouse_binding,
    normalize_key_bindings,
)


def test_key_binding_masks_modifiers() -> None:
    binding = key_binding(Qt.Key_A, Qt.ControlModifier.value | Qt.MetaModifier.value)
    assert binding["key"] == int(Qt.Key_A)
    assert binding["modifiers"] == (Qt.ControlModifier.value & MODIFIER_MASK)


def test_mouse_binding_includes_double_flag() -> None:
    binding = mouse_binding(Qt.LeftButton, Qt.ShiftModifier.value, double=True)
    assert binding["button"] == int(Qt.LeftButton.value)
    assert binding["modifiers"] == Qt.ShiftModifier.value
    assert binding["double"] is True


def test_normalize_key_bindings_uses_defaults_for_invalid_input() -> None:
    normalized = normalize_key_bindings("invalid")
    defaults = default_key_bindings()
    assert normalized.keys() == defaults.keys()


def test_normalize_key_bindings_keeps_valid_entries() -> None:
    value = {
        "open_image": {
            "keyboard": {"key": int(Qt.Key_F5), "modifiers": Qt.ControlModifier.value | Qt.MetaModifier.value},
            "mouse": {"button": int(Qt.LeftButton.value), "modifiers": Qt.ShiftModifier.value, "double": True},
        }
    }
    normalized = normalize_key_bindings(value)
    assert normalized["open_image"]["keyboard"] == {
        "key": int(Qt.Key_F5),
        "modifiers": Qt.ControlModifier.value,
    }
    assert normalized["open_image"]["mouse"] == {
        "button": int(Qt.LeftButton.value),
        "modifiers": Qt.ShiftModifier.value,
        "double": True,
    }


def test_normalize_key_bindings_drops_invalid_bindings() -> None:
    defaults = default_key_bindings()
    value = {
        "open_folder": {
            "keyboard": {"key": -1, "modifiers": 0},
            "mouse": {"button": 0, "modifiers": 0, "double": False},
        }
    }
    normalized = normalize_key_bindings(value)
    assert normalized["open_folder"]["keyboard"] == defaults["open_folder"]["keyboard"]
    assert normalized["open_folder"]["mouse"] == defaults["open_folder"]["mouse"]


def test_duplicate_keyboard_binding_detected() -> None:
    bindings = default_key_bindings()
    bindings["open_image"]["keyboard"] = key_binding(Qt.Key_F2)
    bindings["open_folder"]["keyboard"] = key_binding(Qt.Key_F2)
    duplicates = duplicate_binding_signatures(bindings, "keyboard")
    assert (int(Qt.Key_F2), 0) in duplicates


def test_duplicate_mouse_binding_detected() -> None:
    bindings = default_key_bindings()
    dup = mouse_binding(Qt.MiddleButton, Qt.ControlModifier.value, double=False)
    bindings["open_image"]["mouse"] = dup
    bindings["open_folder"]["mouse"] = dup
    duplicates = duplicate_binding_signatures(bindings, "mouse")
    assert (int(Qt.MiddleButton.value), Qt.ControlModifier.value, False) in duplicates


def test_image_extensions_include_new_formats() -> None:
    assert ".tiff" in IMAGE_EXTENSIONS
    assert ".avif" in IMAGE_EXTENSIONS
    assert ".heic" in IMAGE_EXTENSIONS


def test_load_config_preserves_detached_side_panel_fields(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "setting.json"
    config_path.write_text(
        json.dumps(
            {
                "engine": "realcugan",
                "engine_retry_count": 2,
                "thumbnail_worker_count": 3,
                "side_panel_detached": True,
                "side_panel_position": "left",
                "side_panel_width": 420,
                "side_panel_window_rect": [120, 80, 500, 700],
                "slideshow_interval_sec": 5,
                "page_jump_value": 10,
                "max_safe_image_pixels": 50_000_000,
                "compare_diff_threshold": 15,
                "zoom_label_precision": 2,
                "log_level": "ERROR",
                "recent_dirs": ["/path/to/dir"],
                "bookmarks": ["bookmark1"],
                "favorites": ["fav1"],
                "engine_presets": {"preset1": {"param1": "value1"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    loaded = config.load_config()

    assert loaded.engine_retry_count == 2
    assert loaded.thumbnail_worker_count == 3
    assert loaded.side_panel_detached is True
    assert loaded.side_panel_position == "left"
    assert loaded.side_panel_width == 420
    assert loaded.side_panel_window_rect == [120, 80, 500, 700]
    assert loaded.slideshow_interval_sec == 5
    assert loaded.page_jump_value == 10
    assert loaded.max_safe_image_pixels == 50_000_000
    assert loaded.compare_diff_threshold == 15
    assert loaded.zoom_label_precision == 2
    assert loaded.log_level == "ERROR"
    assert loaded.recent_dirs == ["/path/to/dir"]
    assert loaded.bookmarks == ["bookmark1"]
    assert loaded.favorites == ["fav1"]
    assert loaded.engine_presets == {"preset1": {"param1": "value1"}}


def test_load_config_normalizes_invalid_side_panel_fields(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "setting.json"
    config_path.write_text(
        json.dumps(
            {
                "engine": "realcugan",
                "side_panel_detached": "yes",
                "side_panel_position": "diagonal",
                "side_panel_width": True,
                "side_panel_window_rect": [10, True, 300, 400],
                "thumbnail_worker_count": "bad",
                "engine_retry_count": -1,
                "slideshow_interval_sec": 0,
                "page_jump_value": 0,
                "max_safe_image_pixels": 0,
                "compare_diff_threshold": -10,
                "zoom_label_precision": "bad",
                "log_level": 123,
                "recent_dirs": ["/keep", "", 1],
                "bookmarks": [123, "valid_bookmark"],
                "favorites": "not_a_list",
                "engine_presets": {"preset1": ["invalid"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    loaded = config.load_config()

    assert loaded.side_panel_detached is False
    assert loaded.side_panel_position == "right"
    assert loaded.side_panel_width == 460
    assert loaded.side_panel_window_rect is None
    assert loaded.thumbnail_worker_count == 1
    assert loaded.engine_retry_count == 0
    assert loaded.slideshow_interval_sec == 1
    assert loaded.page_jump_value == 1
    assert loaded.max_safe_image_pixels == 1_000_000
    assert loaded.compare_diff_threshold == 0
    assert loaded.zoom_label_precision == 0
    assert loaded.log_level == "INFO"
    assert loaded.recent_dirs == ["/keep"]
    assert loaded.bookmarks == ["valid_bookmark"]
    assert loaded.favorites == []
    assert loaded.engine_presets == {}
