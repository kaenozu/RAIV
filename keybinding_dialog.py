"""
keybinding_dialog.py

RAIV のキーバインディング設定ダイアログ。

なぜ存在するか:
    キーボード/マウス割り当ての変更UIを独立したダイアログとして提供するため。

関連ファイル:
    - config.py: UIテキスト定数、キーバインディングヘルパー
    - raiv.py: MainWindow から当ダイアログを起動する
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import (
    DIALOG_ACCEPT_TEXT,
    MODIFIER_LABELS,
    BindingValue,
    key_binding,
    key_binding_text,
    mouse_binding,
    mouse_binding_text,
)
from ui_text import translate_binding_text, translate_ui_text


class KeyBindingDialog(QDialog):
    def __init__(self, parent: QWidget, title: str, kind: str, binding: BindingValue | None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.binding = dict(binding) if binding else None
        self.capturing = False
        self.language = parent.ui_language() if hasattr(parent, "ui_language") else "ja"
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        self.capture_button = QPushButton(self.dialog_text("ここをクリック後、設定するキーを押下" if kind == "keyboard" else "ここをクリック後、設定するマウスボタンを押下"))
        self.capture_button.clicked.connect(self.start_capture)
        layout.addWidget(self.capture_button)
        mods = QHBoxLayout()
        self.ctrl_check = QCheckBox(MODIFIER_LABELS[Qt.ControlModifier.value])
        self.shift_check = QCheckBox(MODIFIER_LABELS[Qt.ShiftModifier.value])
        self.alt_check = QCheckBox(MODIFIER_LABELS[Qt.AltModifier.value])
        for checkbox in (self.ctrl_check, self.shift_check, self.alt_check):
            checkbox.stateChanged.connect(self.on_option_changed)
            mods.addWidget(checkbox)
        mods.addStretch(1)
        layout.addLayout(mods)
        self.double_check = QCheckBox(self.dialog_text("ダブルクリック"))
        self.double_check.stateChanged.connect(self.on_option_changed)
        if kind == "mouse":
            layout.addWidget(self.double_check)
        self.preview_label = QLabel()
        layout.addWidget(self.preview_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(DIALOG_ACCEPT_TEXT)
        buttons.button(QDialogButtonBox.Cancel).setText(self.dialog_text("キャンセル"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.load_binding(binding)

    def dialog_text(self, text: str) -> str:
        return translate_ui_text(text, self.language)

    def load_binding(self, binding: BindingValue | None) -> None:
        modifiers = int(binding.get("modifiers", 0)) if binding else 0
        self.ctrl_check.setChecked(bool(modifiers & Qt.ControlModifier.value))
        self.shift_check.setChecked(bool(modifiers & Qt.ShiftModifier.value))
        self.alt_check.setChecked(bool(modifiers & Qt.AltModifier.value))
        if self.kind == "mouse":
            self.double_check.setChecked(bool(binding.get("double", False)) if binding else False)
        self.update_preview()

    def selected_modifiers(self) -> int:
        modifiers = 0
        if self.ctrl_check.isChecked():
            modifiers |= Qt.ControlModifier.value
        if self.shift_check.isChecked():
            modifiers |= Qt.ShiftModifier.value
        if self.alt_check.isChecked():
            modifiers |= Qt.AltModifier.value
        return modifiers

    def start_capture(self) -> None:
        if self.capturing:
            return
        self.capturing = True
        self.capture_button.setText(self.dialog_text("入力待ち... Escで解除"))
        self.capture_button.setFocus()
        self.ctrl_check.setEnabled(False)
        self.shift_check.setEnabled(False)
        self.alt_check.setEnabled(False)
        if self.kind == "mouse":
            self.double_check.setEnabled(False)
        if self.kind == "keyboard":
            self.grabKeyboard()
        else:
            self.grabMouse()

    def on_option_changed(self) -> None:
        if self.binding:
            self.binding["modifiers"] = self.selected_modifiers()
            if self.kind == "mouse":
                self.binding["double"] = self.double_check.isChecked()
        self.update_preview()

    def stop_capture(self) -> None:
        if not self.capturing:
            return
        if self.kind == "keyboard":
            self.releaseKeyboard()
        else:
            self.releaseMouse()
        self.capturing = False
        self.ctrl_check.setEnabled(True)
        self.shift_check.setEnabled(True)
        self.alt_check.setEnabled(True)
        if self.kind == "mouse":
            self.double_check.setEnabled(True)
        self.capture_button.setText(self.dialog_text("ここをクリック後、設定するキーを押下" if self.kind == "keyboard" else "ここをクリック後、設定するマウスボタンを押下"))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self.capturing:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key_Escape:
            self.binding = None
        elif key not in {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta}:
            self.binding = key_binding(key, self.selected_modifiers())
        self.stop_capture()
        self.update_preview()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.capturing or self.kind != "mouse":
            super().mousePressEvent(event)
            return
        self.binding = mouse_binding(event.button(), self.selected_modifiers(), self.double_check.isChecked())
        self.stop_capture()
        self.update_preview()

    def update_preview(self) -> None:
        text = key_binding_text(self.binding) if self.kind == "keyboard" else mouse_binding_text(self.binding)
        text = translate_binding_text(text, self.language)
        self.preview_label.setText(f"{self.dialog_text('現在')}: {text}")

    def reject(self) -> None:
        self.stop_capture()
        super().reject()
