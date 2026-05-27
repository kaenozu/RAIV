"""
config.py

RAIV の設定・定数・キーバインディングヘルパーを定義する。
どのモジュールからも依存されない基底モジュール。

なぜ存在するか:
    設定の直列化/復元、UIテキストの国際化、キーバインディングの管理を
    一箇所にまとめ、他のモジュールから再利用するため。

関連ファイル:
    - raiv.py: このモジュールを import して使用する
    - setting.json: 設定ファイル（自動生成）
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

try:
    from PySide6.QtCore import Signal as QtSignal
except ImportError:
    QtSignal = None


APP_NAME = "Realtime AI Image Viewer"
APP_SHORT_NAME = "RAIV"
APP_ID = "RealtimeAIImageViewer.RAIV"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "setting.json"
APP_ICON_ICO = APP_DIR / "assets" / "app_icon.ico"
APP_ICON_PNG = APP_DIR / "assets" / "app_icon.png"
REALESRGAN_FIXED_SCALE = 4
BUNDLED_REALCUGAN_EXE = APP_DIR / "tools" / "realcugan-ncnn-vulkan" / "realcugan-ncnn-vulkan.exe"
BUNDLED_REALESRGAN_EXE = APP_DIR / "tools" / "realesrgan-ncnn-vulkan" / "realesrgan-ncnn-vulkan.exe"
LEGACY_REALCUGAN_TEMPLATE = 'realcugan-ncnn-vulkan.exe -i "{input}" -o "{output}" -s {scale} -n {denoise} -t {tile}'
DEFAULT_REALCUGAN_TEMPLATE = (
    f'"{BUNDLED_REALCUGAN_EXE}" -i "{{input}}" -o "{{output}}" -s {{scale}} -n {{denoise}} -t {{tile}}'
    if BUNDLED_REALCUGAN_EXE.exists()
    else LEGACY_REALCUGAN_TEMPLATE
)
LEGACY_REALESRGAN_TEMPLATE = 'realesrgan-ncnn-vulkan.exe -i "{input}" -o "{output}" -s {scale} -t {tile} -n {model}'
DEFAULT_REALESRGAN_TEMPLATE = (
    f'"{BUNDLED_REALESRGAN_EXE}" -i "{{input}}" -o "{{output}}" -s {{scale}} -t {{tile}} -n {{model}}'
    if BUNDLED_REALESRGAN_EXE.exists()
    else LEGACY_REALESRGAN_TEMPLATE
)
ENGINE_REALCUGAN = "realcugan"
ENGINE_REALESRGAN = "realesrgan"
ENGINE_LABELS = {
    ENGINE_REALCUGAN: "Real-CUGAN",
    ENGINE_REALESRGAN: "Real-ESRGAN",
}
REALESRGAN_MODELS = ["realesr-animevideov3", "realesrgan-x4plus", "realesrgan-x4plus-anime"]
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif", ".heic", ".heif"}
ARCHIVE_EXTENSIONS = {".zip", ".cbz", ".rar", ".cbr", ".7z", ".cb7"}
TEMP_ARCHIVE_PREFIX = "realcugan_qt_archive_"
TEMP_WORK_PREFIX = "realcugan_qt_work_"
TEMP_OUTPUT_PREFIX = "realcugan_"
TEMP_LOCK_FILE = "viewer.lock"
BORDERLESS_FULLSCREEN_OVERSCAN = 1
FORM_LABEL_WIDTH = 132
MAX_DISPLAY_SCALE = 5.0
PREFETCH_DEBOUNCE_MS = 80
THUMBNAIL_TRIGGER_MARGIN = 48
THUMBNAIL_MIN_HEIGHT = 96
THUMBNAIL_MAX_HEIGHT = 320
THUMBNAIL_RESIZE_GRIP = 10
THUMBNAIL_HIDE_GRACE_SEC = 0.45
THUMBNAIL_HIDE_MARGIN = 28
THUMBNAIL_HIDE_DELAY_MS = 220
SIDE_PANEL_HIDE_GRACE_SEC = 0.45
SIDE_PANEL_HIDE_MARGIN = 36
SIDE_PANEL_HIDE_DELAY_MS = 220
PROFILE_UPDATE_INTERVAL_MS = 500
RESAMPLE_ALGORITHMS = {
    "lanczos3": "Lanczos3",
    "lanczos4": "Lanczos4",
    "bicubic": "Bicubic",
    "area": "Area",
}
MODIFIER_MASK = (
    Qt.ControlModifier.value
    | Qt.ShiftModifier.value
    | Qt.AltModifier.value
)
ACTION_DEFS = [
    ("open_image", "画像を開く"),
    ("open_folder", "フォルダを開く"),
    ("next_page", "次ページ送り"),
    ("previous_page", "前ページ送り"),
    ("last_page", "最終ページ飛ばし"),
    ("first_page", "最初ページ飛ばし"),
    ("toggle_fullscreen", "全画面表示/解除"),
    ("toggle_thumbnail_panel", "サムネイル固定/自動表示"),
    ("toggle_side_panel", "右ペイン固定/自動表示"),
    ("toggle_compare", "比較モードオン/オフ"),
    ("actual_size", "等倍表示"),
    ("fit_view", "画面フィット表示"),
    ("rotate_right", "画像右回転"),
    ("rotate_left", "画像左回転"),
    ("flip_horizontal", "画像左右反転"),
    ("flip_vertical", "画像上下反転"),
]

UI_TEXT_EN = {
    "画像を開く": "Open image",
    "フォルダを開く": "Open folder",
    "次ページ送り": "Next page",
    "前ページ送り": "Previous page",
    "最終ページ飛ばし": "Jump to last page",
    "最初ページ飛ばし": "Jump to first page",
    "全画面表示/解除": "Toggle fullscreen",
    "サムネイル固定/自動表示": "Thumbnail pinned/auto",
    "右ペイン固定/自動表示": "Right panel pinned/auto",
    "比較モードオン/オフ": "Toggle compare mode",
    "等倍表示": "Actual size",
    "画面フィット表示": "Fit to window",
    "画像右回転": "Rotate right",
    "画像左回転": "Rotate left",
    "画像左右反転": "Flip horizontal",
    "画像上下反転": "Flip vertical",
    "設定": "Settings",
    "固定": "Pin",
    "固定中": "Pinned",
    "自動表示": "Auto",
    "エンジン設定": "Engine",
    "全般": "General",
    "キーコンフィグ": "Key Config",
    "エンジン": "Engine",
    "倍率": "Scale",
    "ノイズ": "Denoise",
    "Real-ESRGANモデル": "Real-ESRGAN model",
    "ノイズ: Real-CUGAN専用。-1 はノイズ除去なし。0/1/2/3 は数値が大きいほど強く除去します。": "Denoise: Real-CUGAN only. -1 disables denoising. 0/1/2/3 remove noise more strongly as the value increases.",
    "Real-ESRGANはノイズ値を使わず、モデルで画風や復元傾向を選びます。": "Real-ESRGAN does not use the denoise value. Choose a model to change image style and restoration behavior.",
    "realesr-animevideov3: アニメ/イラスト向けの軽量標準モデル。 realesrgan-x4plus: 写真や一般画像向け。 realesrgan-x4plus-anime: アニメ/イラスト向けのx4plus派生モデル。 RAIVではReal-ESRGAN選択中、倍率は4倍固定として処理します。": "realesr-animevideov3: lightweight standard model for anime/illustration. realesrgan-x4plus: for photos and general images. realesrgan-x4plus-anime: x4plus-derived model for anime/illustration. In RAIV, Real-ESRGAN is processed at fixed 4x scale.",
    "tile: 0 は自動。小さめの値はGPUメモリ使用量を抑えますが、遅くなることがあります。": "tile: 0 is automatic. Smaller values can reduce GPU memory usage but may be slower.",
    "エンジン先読み": "Engine prefetch",
    "選択中の拡大エンジンで処理を先に進める枚数。大きいほど待ち時間を減らせますが、GPU負荷と一時ファイル作成が増えます。": "Number of images to process ahead with the selected engine. Higher values reduce waiting but increase GPU load and temporary files.",
    "縦サイズが閾値以上なら拡大処理しない": "Skip processing when height is at or above threshold",
    "縦サイズ閾値(px)": "Height threshold (px)",
    "モニタ解像度以上の画像をさらに拡大しても表示上の効果は小さく、処理時間とメモリ使用量が増えます。普段使うモニタの縦解像度に合わせる設定が目安です。": "Upscaling images already above monitor resolution often has little visible benefit and increases processing time and memory usage. Set this near your usual monitor height.",
    "拡大結果を倍率フォルダに保存": "Save processed results to scale folder",
    "倍率フォルダがあれば表示に使う": "Use scale folder when available",
    "アーカイブ表示中は保存先フォルダがないため、倍率フォルダ保存と倍率フォルダ読み込みは無効です。": "Scale-folder saving/loading is disabled while viewing archives because there is no output folder.",
    "再実行": "Run again",
    "コマンドテンプレート": "Command template",
    "エンジンexeを選択": "Select engine exe",
    "使用できる置換: {input} {output} {scale} {denoise} {tile} {model}": "Available placeholders: {input} {output} {scale} {denoise} {tile} {model}",
    "次回起動時に古い一時ファイルを削除": "Delete old temporary files on next startup",
    "表示言語": "Language",
    "ビューアー先読み": "Viewer prefetch",
    "表示用に画像をメモリへ先読みする枚数。大きいほどページ送りは速くなりますが、メモリ使用量が増えます。": "Number of images to preload into memory for display. Higher values make page navigation faster but use more memory.",
    "CPUリサンプルキャッシュを使う": "Use CPU resample cache",
    "表示リサンプル方式": "Display resampling method",
    "原寸と異なる表示サイズの画像を、よりきれいに見えるよう作成して保持します。オフにすると標準の高速表示になります。": "Creates and keeps high-quality display-size images when shown at a different size. Turn off for standard fast display.",
    "Lanczos3: 精細で標準的。Lanczos4: より鋭いがリンギングが出ることがあります。Bicubic: やや柔らかく自然。Area: 大きく縮小する時に安定し、ジャギーを抑えやすい方式です。": "Lanczos3: sharp and standard. Lanczos4: sharper but may introduce ringing. Bicubic: softer and natural. Area: stable for large reductions and helps reduce jaggies.",
    "Lanczos4はOpenCVがある環境ではLanczos4、ない環境ではLanczos3相当で処理します。": "Lanczos4 uses OpenCV when available; otherwise it falls back to Lanczos3-equivalent processing.",
    "選択": "Select",
    "背景色": "Background color",
    "比較モード": "Compare mode",
    "比較スライダー": "Compare slider",
    "中央に戻す": "Center",
    "境界線色": "Divider color",
    "境界線の太さ(px)": "Divider width (px)",
    "比較の左右を入れ替える": "Swap compare sides",
    "比較中はShift+ドラッグで境界線を動かす": "Use Shift+drag to move divider in compare mode",
    "ズーム: 100%": "Zoom: 100%",
    "表示を中央へリセット": "Reset view to center",
    "ページ送り間隔(ms)": "Page interval (ms)",
    "ホイールやキー操作で連続ページ送りする時の間隔。0 は最短です。": "Interval used for continuous page navigation by wheel or key. 0 is the shortest.",
    "ページ位置": "Page position",
    "ページ位置スライダーの左右を入れ替える": "Reverse page position slider",
    "オンにすると、ページ位置スライダーとサムネイル列の左右方向が連動して入れ替わります。": "When enabled, the page position slider and thumbnail strip directions are reversed together.",
    "画面下部にサムネイルを表示する": "Show thumbnails at bottom",
    "オフにするとサムネイル生成処理も停止します。大量の画像を開く時に、初期表示や先読みを軽くできます。": "Turning this off also stops thumbnail generation, which can make initial display and prefetch lighter for large folders.",
    "サムネイル列を固定表示する": "Pin thumbnail strip",
    "最後/最初でページ送りしたら反対側へ移動": "Wrap around at first/last page",
    "ページ送り時にズームと表示位置を維持": "Preserve zoom and position when changing pages",
    "マウス横スクロールでページ送り": "Use horizontal mouse wheel for page navigation",
    "横スクロールのページ送り方向を反転": "Reverse horizontal wheel direction",
    "全画面表示時にマウスカーソルを非表示": "Hide mouse cursor in fullscreen",
    "画像またはフォルダ/アーカイブをドロップしてください": "Drop an image, folder, or archive",
    "状態": "Status",
    "ログを表示": "Show log",
    "拡大前メモリ読込": "Original memory load",
    "拡大画像生成": "Processed image generation",
    "拡大後メモリ読込": "Processed memory load",
    "表示用QPixmap": "Display QPixmap",
    "ログ": "Log",
    "内部プロファイリングを表示": "Show internal profiling",
    "設定値をクリックすると割当を変更できます。Escを入力すると未割当に戻ります。Spaceは次ページ、Backspaceは前ページとして固定です。": "Click a binding value to change it. Press Esc to clear it. Space is fixed to next page and Backspace is fixed to previous page.",
    "機能": "Action",
    "キーボード": "Keyboard",
    "マウス": "Mouse",
    "キーコンフィグを初期値に戻す": "Reset key config to defaults",
    "重複しているため、この割当は無効です。": "This binding is duplicated and disabled.",
    "未割当": "Unassigned",
    "左クリック": "Left click",
    "右クリック": "Right click",
    "ホイールクリック": "Middle click",
    "戻るボタン": "Back button",
    "進むボタン": "Forward button",
    "左ダブルクリック": "Left double click",
    "右ダブルクリック": "Right double click",
    "ホイールダブルクリック": "Middle double click",
    "戻るボタンダブルクリック": "Back button double click",
    "進むボタンダブルクリック": "Forward button double click",
    "現在": "Current",
    "キャンセル": "Cancel",
    "入力待ち... Escで解除": "Waiting for input... Esc clears",
    "ここをクリック後、設定するキーを押下": "Click here, then press a key",
    "ここをクリック後、設定するマウスボタンを押下": "Click here, then press a mouse button",
    "ダブルクリック": "Double click",
    "画像ファイル、画像フォルダ、またはアーカイブを指定してください。": "Please select an image file, image folder, or archive.",
    "対応画像がありません。": "No supported images found.",
    "このアーカイブには対応画像がありません。": "This archive contains no supported images.",
}

UI_TEXT_JA = {value: key for key, value in UI_TEXT_EN.items()}


def key_binding(key: Qt.Key | int, modifiers: int = 0) -> dict[str, int]:
    return {"key": int(key), "modifiers": int(modifiers) & MODIFIER_MASK}


def mouse_binding(button: Qt.MouseButton | int, modifiers: int = 0, double: bool = False) -> dict[str, int | bool]:
    return {
        "button": int(button.value if hasattr(button, "value") else button),
        "modifiers": int(modifiers) & MODIFIER_MASK,
        "double": bool(double),
    }


def default_key_bindings() -> dict[str, dict[str, dict | None]]:
    return {
        "open_image": {"keyboard": key_binding(Qt.Key_O), "mouse": None},
        "open_folder": {"keyboard": key_binding(Qt.Key_F), "mouse": None},
        "next_page": {"keyboard": key_binding(Qt.Key_Left), "mouse": None},
        "previous_page": {"keyboard": key_binding(Qt.Key_Right), "mouse": None},
        "last_page": {"keyboard": None, "mouse": mouse_binding(Qt.ForwardButton)},
        "first_page": {"keyboard": None, "mouse": mouse_binding(Qt.BackButton)},
        "toggle_fullscreen": {"keyboard": None, "mouse": mouse_binding(Qt.MiddleButton)},
        "toggle_thumbnail_panel": {"keyboard": key_binding(Qt.Key_F3), "mouse": None},
        "toggle_side_panel": {"keyboard": key_binding(Qt.Key_F4), "mouse": None},
        "toggle_compare": {"keyboard": None, "mouse": None},
        "actual_size": {"keyboard": None, "mouse": mouse_binding(Qt.RightButton, double=True)},
        "fit_view": {"keyboard": None, "mouse": mouse_binding(Qt.LeftButton, double=True)},
        "rotate_right": {"keyboard": key_binding(Qt.Key_R), "mouse": None},
        "rotate_left": {"keyboard": key_binding(Qt.Key_L), "mouse": None},
        "flip_horizontal": {"keyboard": key_binding(Qt.Key_H), "mouse": None},
        "flip_vertical": {"keyboard": key_binding(Qt.Key_V), "mouse": None},
    }


@dataclass
class AppConfig:
    engine: str = ENGINE_REALCUGAN
    command_template: str = DEFAULT_REALCUGAN_TEMPLATE
    realcugan_command_template: str = DEFAULT_REALCUGAN_TEMPLATE
    realesrgan_command_template: str = DEFAULT_REALESRGAN_TEMPLATE
    scale: int = 2
    denoise: int = 0
    tile: int = 0
    realesrgan_model: str = "realesr-animevideov3"
    realcugan_prefetch_count: int = 10
    viewer_prefetch_count: int = 20
    save_upscaled_to_scale_folder: bool = False
    use_scale_folder_cache: bool = True
    skip_realcugan_for_tall_images: bool = True
    skip_realcugan_height_threshold: int = 2160
    background_color: str = "#000000"
    cpu_resample_cache_enabled: bool = True
    cpu_resample_algorithm: str = "lanczos3"
    compare_enabled: bool = False
    compare_split: int = 500
    compare_line_color: str = "#ffffff"
    compare_line_width: int = 2
    compare_swap_sides: bool = False
    compare_shift_drag_moves_boundary: bool = False
    hide_cursor_in_fullscreen: bool = False
    show_log_panel: bool = False
    show_profile_panel: bool = False
    ui_language: str = "ja"
    thumbnail_enabled: bool = True
    thumbnail_pinned: bool = False
    thumbnail_size: int = 96
    thumbnail_height: int = 142
    horizontal_wheel_navigation: bool = False
    horizontal_wheel_inverted: bool = False
    wrap_page_navigation: bool = False
    preserve_view_on_page_navigation: bool = False
    invert_page_position_slider: bool = True
    page_scroll_interval_ms: int = 1
    arrow_right_next: bool = True
    key_bindings: dict[str, dict[str, dict | None]] = field(default_factory=default_key_bindings)
    cleanup_temp_on_start: bool = False
    settings_tab: str = "realcugan"
    window_rect: list[int] | None = None
    window_maximized: bool = False
    window_geometry: str = ""
    side_panel_visible: bool = True
    side_panel_pinned: bool = True
    side_panel_width: int = 460
    splitter_sizes: list[int] | None = None
    last_dir: str = ""


def set_process_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def enable_high_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def command_executable_exists(command: str) -> bool:
    stripped = command.strip()
    if not stripped:
        return False
    if stripped.startswith('"'):
        end = stripped.find('"', 1)
        token = stripped[1:end] if end > 1 else ""
    else:
        token = stripped.split(maxsplit=1)[0]
    if not token:
        return False
    exe_path = Path(os.path.expandvars(token))
    if exe_path.is_absolute():
        return exe_path.is_file()
    return (APP_DIR / exe_path).is_file() or shutil.which(token) is not None


def normalize_key_bindings(value: object) -> dict[str, dict[str, dict | None]]:
    defaults = default_key_bindings()
    if not isinstance(value, dict):
        return defaults
    normalized = defaults
    for action_id, parts in value.items():
        if action_id not in normalized or not isinstance(parts, dict):
            continue
        for kind in ("keyboard", "mouse"):
            binding = parts.get(kind)
            if binding is None:
                normalized[action_id][kind] = None
                continue
            if not isinstance(binding, dict):
                continue
            if kind == "keyboard":
                key = binding.get("key")
                if isinstance(key, int) and key > 0:
                    normalized[action_id][kind] = {
                        "key": key,
                        "modifiers": int(binding.get("modifiers", 0)) & MODIFIER_MASK,
                    }
            else:
                button = binding.get("button")
                if isinstance(button, int) and button > 0:
                    normalized[action_id][kind] = {
                        "button": button,
                        "modifiers": int(binding.get("modifiers", 0)) & MODIFIER_MASK,
                        "double": bool(binding.get("double", False)),
                    }
    return normalized


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        config = AppConfig(**{**asdict(AppConfig()), **data})
        if config.command_template == LEGACY_REALCUGAN_TEMPLATE and BUNDLED_REALCUGAN_EXE.exists():
            config.command_template = DEFAULT_REALCUGAN_TEMPLATE
        if config.realcugan_command_template in {LEGACY_REALCUGAN_TEMPLATE, ""} and BUNDLED_REALCUGAN_EXE.exists():
            config.realcugan_command_template = DEFAULT_REALCUGAN_TEMPLATE
        if config.realesrgan_command_template in {LEGACY_REALESRGAN_TEMPLATE, ""} and BUNDLED_REALESRGAN_EXE.exists():
            config.realesrgan_command_template = DEFAULT_REALESRGAN_TEMPLATE
        if "realcugan_command_template" not in data:
            config.realcugan_command_template = config.command_template or DEFAULT_REALCUGAN_TEMPLATE
        if config.engine not in ENGINE_LABELS:
            config.engine = ENGINE_REALCUGAN
        if config.realesrgan_model not in REALESRGAN_MODELS:
            config.realesrgan_model = REALESRGAN_MODELS[0]
        if config.cpu_resample_algorithm not in RESAMPLE_ALGORITHMS:
            config.cpu_resample_algorithm = "lanczos3"
        if config.ui_language not in {"ja", "en"}:
            config.ui_language = "ja"
        config.key_bindings = normalize_key_bindings(getattr(config, "key_bindings", None))
        if BUNDLED_REALCUGAN_EXE.exists() and not command_executable_exists(config.realcugan_command_template):
            config.realcugan_command_template = DEFAULT_REALCUGAN_TEMPLATE
        if BUNDLED_REALESRGAN_EXE.exists() and not command_executable_exists(config.realesrgan_command_template):
            config.realesrgan_command_template = DEFAULT_REALESRGAN_TEMPLATE
        if "compare_split" in data and 0 <= int(data.get("compare_split", 500)) <= 100:
            config.compare_split = int(data["compare_split"]) * 10
        return config
    except Exception:
        return AppConfig()


def save_config(config: AppConfig) -> None:
    CONFIG_PATH.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")


def modifier_value(modifiers) -> int:
    return int(modifiers.value if hasattr(modifiers, "value") else modifiers) & MODIFIER_MASK


def binding_modifiers_text(modifiers: int) -> list[str]:
    names = []
    if modifiers & Qt.ControlModifier.value:
        names.append("Ctrl")
    if modifiers & Qt.ShiftModifier.value:
        names.append("Shift")
    if modifiers & Qt.AltModifier.value:
        names.append("Alt")
    return names


def key_binding_text(binding: dict | None) -> str:
    if not binding:
        return "未割当"
    parts = binding_modifiers_text(int(binding.get("modifiers", 0)))
    key = int(binding.get("key", 0))
    key_text = QKeySequence(key).toString(QKeySequence.NativeText) if key else ""
    parts.append(key_text or f"Key {key}")
    return "+".join(parts)


def mouse_binding_text(binding: dict | None) -> str:
    if not binding:
        return "未割当"
    parts = binding_modifiers_text(int(binding.get("modifiers", 0)))
    button = int(binding.get("button", 0))
    names = {
        Qt.LeftButton.value: "左クリック",
        Qt.RightButton.value: "右クリック",
        Qt.MiddleButton.value: "ホイールクリック",
        Qt.BackButton.value: "戻るボタン",
        Qt.ForwardButton.value: "進むボタン",
    }
    button_text = names.get(button, f"ボタン{button}")
    if binding.get("double"):
        button_text = button_text.replace("クリック", "ダブルクリック")
        if "ダブルクリック" not in button_text:
            button_text = f"{button_text}ダブルクリック"
    parts.append(button_text)
    return "+".join(parts)


def keyboard_signature(binding: dict | None) -> tuple[int, int] | None:
    if not binding:
        return None
    key = int(binding.get("key", 0))
    if key <= 0:
        return None
    return key, int(binding.get("modifiers", 0)) & MODIFIER_MASK


def mouse_signature(binding: dict | None) -> tuple[int, int, bool] | None:
    if not binding:
        return None
    button = int(binding.get("button", 0))
    if button <= 0:
        return None
    return button, int(binding.get("modifiers", 0)) & MODIFIER_MASK, bool(binding.get("double", False))


def duplicate_binding_signatures(bindings: dict[str, dict[str, dict | None]], kind: str) -> set[tuple]:
    seen: dict[tuple, str] = {}
    duplicates: set[tuple] = set()
    if kind == "keyboard":
        seen[(int(Qt.Key_Space), 0)] = "__fixed_space__"
        seen[(int(Qt.Key_Backspace), 0)] = "__fixed_backspace__"
        signature_func = keyboard_signature
    else:
        signature_func = mouse_signature
    for action_id, action_bindings in bindings.items():
        if not isinstance(action_bindings, dict):
            continue
        signature = signature_func(action_bindings.get(kind))
        if signature is None:
            continue
        if signature in seen:
            duplicates.add(signature)
        else:
            seen[signature] = action_id
    return duplicates
