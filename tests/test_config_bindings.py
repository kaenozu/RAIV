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


def test_load_config_normalizes_invalid_side_panel_fields(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "setting.json"
    config_path.write_text(
        json.dumps(
            {
                "engine": "realcugan",
                "side_panel_detached": "yes",
                "side_panel_position": "diagonal",
                "side_panel_width": 100,
                "side_panel_window_rect": [10, "bad", 300, 400],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", config_path)

    loaded = config.load_config()

    assert loaded.side_panel_detached is False
    assert loaded.side_panel_position == "right"
    assert loaded.side_panel_width == 240
    assert loaded.side_panel_window_rect is None
