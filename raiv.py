"""
raiv.py

Realtime AI Image Viewer (RAIV) のメインエントリポイント。
画像ビューアーアプリケーション全体を定義する。PySide6 を用いた GUI、OpenGL 表示、
Real-CUGAN / Real-ESRGAN による超解像処理、アーカイブ展開、サムネイル管理、
キーコンフィグ、プロファイリングなどを含む。

なぜ存在するか:
    RAIV は画像を開くだけで AI 超解像処理済み画像を表示する Windows 向けビューアー。
    本ファイルは全機能を実装する単一モジュール。

関連ファイル:
    - assets/app_icon.ico / app_icon.png: アプリアイコン
    - tools/realcugan-ncnn-vulkan/: Real-CUGAN 実行バイナリ
    - tools/realesrgan-ncnn-vulkan/: Real-ESRGAN 実行バイナリ
    - setting.json: 設定ファイル（自動生成）
"""

from __future__ import annotations

import argparse
import config as config_module
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from archive_utils import (
    archive_member_output_path as build_archive_member_output_path,
)
from archive_utils import (
    archive_open_error_message as build_archive_open_error_message,
)
from archive_utils import (
    collect_archive_outputs as collect_extracted_archive_outputs,
)
from archive_utils import (
    extract_archive_images as extract_archive_images_impl,
)
from archive_utils import (
    extract_rar_images as extract_rar_images_impl,
)
from archive_utils import (
    extract_with_7z_command as extract_with_7z_command_impl,
)
from archive_utils import (
    extract_zip_images as extract_zip_images_impl,
)
from archive_utils import (
    find_7z as find_7z_command,
)
from config import (
    ACTION_DEFS,
    APP_DIR,
    APP_ICON_ICO,
    APP_ICON_PNG,
    APP_NAME,
    APP_SHORT_NAME,
    ARCHIVE_EXTENSIONS,
    BORDERLESS_FULLSCREEN_OVERSCAN,
    BUNDLED_REALCUGAN_EXE,
    BUNDLED_REALESRGAN_EXE,
    CONFIG_PATH,
    CONFIG_BACKUP_PATH,
    DEFAULT_BACKGROUND_COLOR,
    DEFAULT_REALCUGAN_TEMPLATE,
    DEFAULT_REALESRGAN_TEMPLATE,
    DIALOG_ACCEPT_TEXT,
    ENABLE_COMPARE_MODE,
    ENGINE_LABELS,
    ENGINE_REALCUGAN,
    ENGINE_REALESRGAN,
    FORM_LABEL_WIDTH,
    IMAGE_EXTENSIONS,
    MAX_ENGINE_RETRY_COUNT,
    MAX_THUMBNAIL_WORKER_COUNT,
    PREFETCH_DEBOUNCE_MS,
    PROFILE_UPDATE_INTERVAL_MS,
    REALESRGAN_FIXED_SCALE,
    REALESRGAN_MODELS,
    RESAMPLE_ALGORITHMS,
    SETTINGS_TABS,
    SIDE_PANEL_HIDE_DELAY_MS,
    SIDE_PANEL_HIDE_GRACE_SEC,
    SIDE_PANEL_HIDE_MARGIN,
    SIDE_PANEL_POSITIONS,
    SORT_MODES,
    TEMP_ARCHIVE_PREFIX,
    TEMP_LOCK_FILE,
    TEMP_OUTPUT_PREFIX,
    TEMP_WORK_PREFIX,
    THUMBNAIL_HIDE_DELAY_MS,
    THUMBNAIL_HIDE_GRACE_SEC,
    THUMBNAIL_HIDE_MARGIN,
    THUMBNAIL_MAX_HEIGHT,
    THUMBNAIL_MIN_HEIGHT,
    THUMBNAIL_RESIZE_GRIP,
    AppConfig,
    ArchiveDisplayMap,
    BindingValue,
    CompareConfigDomain,
    EngineConfigDomain,
    ProcessingKey,
    UiConfigDomain,
    ViewerConfigDomain,
    coerce_float,
    coerce_int,
    command_executable_exists,
    default_key_bindings,
    duplicate_binding_signatures,
    enable_high_dpi_awareness,
    key_binding_text,
    keyboard_signature,
    modifier_value,
    mouse_binding_text,
    mouse_signature,
    normalize_key_bindings,
    set_process_app_user_model_id,
)
from exceptions import ArchiveError
from helpers import archive_display_name, cleanup_stale_temp_entries, format_command_template, sort_images, split_command_line
from keybinding_dialog import KeyBindingDialog
from logging_utils import (
    LOG_LEVEL_ERROR,
    LOG_LEVEL_INFO,
    LOG_LEVEL_RANK,
    LOG_LEVEL_WARN,
    LOG_LEVELS,
    can_emit_log,
)
from renderer_utils import compose_side_by_side_images
from ui_text import translate_binding_text, translate_state_text, translate_ui_text
from viewer import AppSignals, GLImageView

try:
    from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer
    from PySide6.QtGui import (
        QCloseEvent,
        QColor,
        QCursor,
        QDragLeaveEvent,
        QIcon,
        QImage,
        QImageReader,
        QKeyEvent,
        QPixmap,
        QResizeEvent,
    )
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListView,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QProgressBar,
        QProgressDialog,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSlider,
        QSpinBox,
        QSplitter,
        QTabWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise SystemExit(
        "PySide6 が見つかりません。install_support.bat を実行してください。"
    ) from exc

try:
    import rarfile
except ImportError:
    rarfile = None

try:
    import py7zr
except ImportError:
    py7zr = None

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import numpy as np
except ImportError:
    np = None

try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:
    QPdfDocument = None


@dataclass
class RuntimeState:
    image_paths: list[Path] = field(default_factory=list)
    image_path_set: set[Path] = field(default_factory=set)
    image_path_string_set: set[str] = field(default_factory=set)
    current_index: int = -1
    last_navigation_step: int = 1
    folder_list_loading: bool = False
    deferred_page_steps: int = 0
    pdf_load_session_id: int = 0
    pdf_expected_pages: int = 0
    pdf_loaded_pages: int = 0
    pdf_loading: bool = False
    navigation_history: list[int] = field(default_factory=list)
    navigation_history_cursor: int = -1
    navigation_history_blocked: bool = False
    view_snapshots: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass
class UiRuntimeState:
    side_panel_visible_before_fullscreen: bool = True
    side_panel_width: int = 460
    fullscreen_cursor_hidden: bool = False
    side_panel_overlay: bool = False
    borderless_fullscreen: bool = False
    fullscreen_enforce_pending: bool = False
    overlay_resizing: bool = False
    overlay_modal_guard: bool = False
    overlay_hide_suppressed_until: float = 0.0
    adjusting_splitter: bool = False
    closing: bool = False


PDF_RENDER_SCALE = 1.5
PDF_MAX_RENDER_PIXELS = 4_000_000
PDF_PROGRESS_EVENT_INTERVAL_SEC = 0.05


def _pdf_target_size(page_size, render_scale: float, max_render_pixels: int) -> QSize:
    width = max(1, int(round(page_size.width() * render_scale)))
    height = max(1, int(round(page_size.height() * render_scale)))

    if max_render_pixels > 0:
        pixel_count = width * height
        if pixel_count > max_render_pixels:
            ratio = (max_render_pixels / float(pixel_count)) ** 0.5
            width = max(1, int(width * ratio))
            height = max(1, int(height * ratio))

    return QSize(width, height)


def _render_pdf_page_image(
    document: object,
    pdf_path: Path,
    temp_dir: Path,
    page_index: int,
    render_scale: float,
    max_render_pixels: int,
) -> Path:
    page_size = document.pagePointSize(page_index)
    if page_size.width() <= 0 or page_size.height() <= 0:
        raise ArchiveError(f"Invalid PDF page size at page {page_index + 1}")
    target_size = _pdf_target_size(page_size, render_scale, max_render_pixels)
    image = document.render(page_index, target_size)
    if image.isNull():
        raise ArchiveError(f"Failed to render PDF page {page_index + 1}")
    output_path = temp_dir / f"{pdf_path.stem}_page_{page_index + 1:04d}.png"
    if not image.save(str(output_path), "PNG"):
        raise ArchiveError(f"Failed to save PDF page {page_index + 1}")
    return output_path


def render_pdf_pages_to_images(
    pdf_path: Path,
    temp_dir: Path,
    render_scale: float = PDF_RENDER_SCALE,
    max_render_pixels: int = PDF_MAX_RENDER_PIXELS,
    progress_callback: Callable[[int, int], bool] | None = None,
) -> tuple[list[Path], ArchiveDisplayMap]:
    if QPdfDocument is None:
        raise ArchiveError("PDF support is unavailable.")
    document = QPdfDocument()
    document.load(str(pdf_path))
    if document.error() != QPdfDocument.Error.None_:
        raise ArchiveError("PDF decoder error")
    page_count = document.pageCount()
    if page_count <= 0:
        return [], {}

    if progress_callback is not None and not progress_callback(0, page_count):
        raise ArchiveError("PDF open cancelled")

    images: list[Path] = []
    names: ArchiveDisplayMap = {}
    for page_index in range(page_count):
        page_size = document.pagePointSize(page_index)
        if page_size.width() <= 0 or page_size.height() <= 0:
            raise ArchiveError(f"Invalid PDF page size at page {page_index + 1}")
        target_size = _pdf_target_size(page_size, render_scale, max_render_pixels)
        image = document.render(page_index, target_size)
        if image.isNull():
            raise ArchiveError(f"Failed to render PDF page {page_index + 1}")
        output_path = temp_dir / f"{pdf_path.stem}_page_{page_index + 1:04d}.png"
        if not image.save(str(output_path), "PNG"):
            raise ArchiveError(f"Failed to save PDF page {page_index + 1}")
        images.append(output_path)
        names[output_path] = f"{pdf_path.name} [page {page_index + 1}]"
        if progress_callback is not None and not progress_callback(page_index + 1, page_count):
            raise ArchiveError("PDF open cancelled")
    return images, names


def _sync_config_module_paths() -> None:
    config_module.APP_DIR = APP_DIR
    config_module.CONFIG_PATH = CONFIG_PATH
    config_module.CONFIG_BACKUP_PATH = CONFIG_BACKUP_PATH


def load_config() -> AppConfig:
    _sync_config_module_paths()
    return config_module.load_config()


def save_config(config: AppConfig) -> None:
    _sync_config_module_paths()
    config_module.save_config(config)


class MainWindow(QMainWindow):
    def __init__(self, initial_path: str = "", forced_language: str = "") -> None:
        super().__init__()
        self.initializing = True
        self.startup_messages: list[tuple[str, str]] = []
        self.config_data = load_config()
        self.duplicate_keyboard_bindings = duplicate_binding_signatures(self.config_data.key_bindings, "keyboard")
        self.show_log_panel = self.config_data.show_log_panel
        if self.config_data.cleanup_temp_on_start:
            removed_count, cleanup_errors = self._cleanup_stale_temp_files()
            if removed_count:
                self.startup_messages.append((LOG_LEVEL_INFO, f"Cleaned stale temporary folders/files: {removed_count}"))
            for error_text in cleanup_errors:
                self.startup_messages.append((LOG_LEVEL_WARN, error_text))
            self.config_data.cleanup_temp_on_start = False
            save_config(self.config_data)

        self.signals = AppSignals()
        self._init_signals()
        self._init_state()
        self._init_ui()
        self._apply_settings_to_viewer()
        if forced_language in {"ja", "en"}:
            self.config_data.ui_language = forced_language
            if hasattr(self, "language_combo"):
                self.language_combo.setCurrentIndex(0 if forced_language == "ja" else 1)
            self.apply_language()
        QTimer.singleShot(0, self.run_startup_self_check)
        self.initializing = False
        self._init_workers()
        if initial_path:
            QTimer.singleShot(0, lambda p=initial_path: self.open_path_deferred(Path(p)))

    @property
    def image_paths(self) -> list[Path]:
        return self.runtime_state.image_paths

    @image_paths.setter
    def image_paths(self, value: list[Path]) -> None:
        self.runtime_state.image_paths = value

    @property
    def image_path_set(self) -> set[Path]:
        return self.runtime_state.image_path_set

    @image_path_set.setter
    def image_path_set(self, value: set[Path]) -> None:
        self.runtime_state.image_path_set = value

    @property
    def image_path_string_set(self) -> set[str]:
        return self.runtime_state.image_path_string_set

    @image_path_string_set.setter
    def image_path_string_set(self, value: set[str]) -> None:
        self.runtime_state.image_path_string_set = value

    @property
    def current_index(self) -> int:
        return self.runtime_state.current_index

    @current_index.setter
    def current_index(self, value: int) -> None:
        self.runtime_state.current_index = value

    @property
    def last_navigation_step(self) -> int:
        return self.runtime_state.last_navigation_step

    @last_navigation_step.setter
    def last_navigation_step(self, value: int) -> None:
        self.runtime_state.last_navigation_step = value

    @property
    def folder_list_loading(self) -> bool:
        return self.runtime_state.folder_list_loading

    @folder_list_loading.setter
    def folder_list_loading(self, value: bool) -> None:
        self.runtime_state.folder_list_loading = value

    @property
    def deferred_page_steps(self) -> int:
        return self.runtime_state.deferred_page_steps

    @deferred_page_steps.setter
    def deferred_page_steps(self, value: int) -> None:
        self.runtime_state.deferred_page_steps = value

    @property
    def navigation_history(self) -> list[int]:
        return self.runtime_state.navigation_history

    @navigation_history.setter
    def navigation_history(self, value: list[int]) -> None:
        self.runtime_state.navigation_history = value

    @property
    def navigation_history_cursor(self) -> int:
        return self.runtime_state.navigation_history_cursor

    @navigation_history_cursor.setter
    def navigation_history_cursor(self, value: int) -> None:
        self.runtime_state.navigation_history_cursor = value

    @property
    def navigation_history_blocked(self) -> bool:
        return self.runtime_state.navigation_history_blocked

    @navigation_history_blocked.setter
    def navigation_history_blocked(self, value: bool) -> None:
        self.runtime_state.navigation_history_blocked = value

    @property
    def view_snapshots(self) -> dict[str, dict[str, object]]:
        return self.runtime_state.view_snapshots

    @view_snapshots.setter
    def view_snapshots(self, value: dict[str, dict[str, object]]) -> None:
        self.runtime_state.view_snapshots = value

    @property
    def side_panel_visible_before_fullscreen(self) -> bool:
        return self.ui_runtime_state.side_panel_visible_before_fullscreen

    @side_panel_visible_before_fullscreen.setter
    def side_panel_visible_before_fullscreen(self, value: bool) -> None:
        self.ui_runtime_state.side_panel_visible_before_fullscreen = value

    @property
    def side_panel_width(self) -> int:
        return self.ui_runtime_state.side_panel_width

    @side_panel_width.setter
    def side_panel_width(self, value: int) -> None:
        self.ui_runtime_state.side_panel_width = value

    @property
    def fullscreen_cursor_hidden(self) -> bool:
        return self.ui_runtime_state.fullscreen_cursor_hidden

    @fullscreen_cursor_hidden.setter
    def fullscreen_cursor_hidden(self, value: bool) -> None:
        self.ui_runtime_state.fullscreen_cursor_hidden = value

    @property
    def side_panel_overlay(self) -> bool:
        return self.ui_runtime_state.side_panel_overlay

    @side_panel_overlay.setter
    def side_panel_overlay(self, value: bool) -> None:
        self.ui_runtime_state.side_panel_overlay = value

    @property
    def borderless_fullscreen(self) -> bool:
        return self.ui_runtime_state.borderless_fullscreen

    @borderless_fullscreen.setter
    def borderless_fullscreen(self, value: bool) -> None:
        self.ui_runtime_state.borderless_fullscreen = value

    @property
    def fullscreen_enforce_pending(self) -> bool:
        return self.ui_runtime_state.fullscreen_enforce_pending

    @fullscreen_enforce_pending.setter
    def fullscreen_enforce_pending(self, value: bool) -> None:
        self.ui_runtime_state.fullscreen_enforce_pending = value

    @property
    def overlay_resizing(self) -> bool:
        return self.ui_runtime_state.overlay_resizing

    @overlay_resizing.setter
    def overlay_resizing(self, value: bool) -> None:
        self.ui_runtime_state.overlay_resizing = value

    @property
    def overlay_modal_guard(self) -> bool:
        return self.ui_runtime_state.overlay_modal_guard

    @overlay_modal_guard.setter
    def overlay_modal_guard(self, value: bool) -> None:
        self.ui_runtime_state.overlay_modal_guard = value

    @property
    def overlay_hide_suppressed_until(self) -> float:
        return self.ui_runtime_state.overlay_hide_suppressed_until

    @overlay_hide_suppressed_until.setter
    def overlay_hide_suppressed_until(self, value: float) -> None:
        self.ui_runtime_state.overlay_hide_suppressed_until = value

    @property
    def adjusting_splitter(self) -> bool:
        return self.ui_runtime_state.adjusting_splitter

    @adjusting_splitter.setter
    def adjusting_splitter(self, value: bool) -> None:
        self.ui_runtime_state.adjusting_splitter = value

    @property
    def closing(self) -> bool:
        return self.ui_runtime_state.closing

    @closing.setter
    def closing(self, value: bool) -> None:
        self.ui_runtime_state.closing = value

    def _init_signals(self) -> None:
        assert isinstance(self.signals, AppSignals)
        self.signals.process_started.connect(self.on_process_started)
        self.signals.process_done.connect(self.on_process_done)
        self.signals.folder_images_ready.connect(self.on_folder_images_ready)
        self.signals.pdf_page_ready.connect(self.on_pdf_page_ready)
        self.signals.pdf_load_done.connect(self.on_pdf_load_done)
        self.signals.pdf_load_failed.connect(self.on_pdf_load_failed)
        self.signals.prefetch_done.connect(self.on_prefetch_done)
        self.signals.thumbnail_done.connect(self.on_thumbnail_done)
        self.signals.profile_event.connect(self.record_profile)

    def _init_state(self) -> None:
        self.runtime_state = RuntimeState()
        self.ui_runtime_state = UiRuntimeState(side_panel_width=int(self.config_data.side_panel_width))
        self.thumbnail_workers: list[threading.Thread] = []
        self.slideshow_timer = QTimer(self)
        self.slideshow_timer.timeout.connect(self.on_slideshow_tick)
        self.original_cache: OrderedDict[Path, QImage] = OrderedDict()
        self.failed_original_paths: set[Path] = set()
        self.original_cache_lock = threading.Lock()
        self.processed_cache: OrderedDict[ProcessingKey, QImage] = OrderedDict()
        self.processed_cache_limit = 200
        self.processing_paths: set[Path] = set()
        self.queued_paths: set[Path] = set()
        self.work_queue: queue.Queue[Path | None] = queue.Queue()
        self.prefetch_io_queue: queue.PriorityQueue[tuple[int, int, int, str, object, str, str]] = queue.PriorityQueue()
        self.prefetch_io_sequence = 0
        self.prefetch_io_lock = threading.Lock()
        self.thumbnail_queue: queue.PriorityQueue[tuple[int, int, int, int, str]] = queue.PriorityQueue()
        self.thumbnail_sequence = 0
        self.thumbnail_lock = threading.Lock()
        self.thumbnail_generation = 0
        self.thumbnail_pending: set[int] = set()
        self.thumbnail_ready_indexes: set[int] = set()
        self.thumbnail_items: list[QListWidgetItem | None] = []
        self.thumbnail_overlay_visible = False
        self.thumbnail_height = int(self.config_data.thumbnail_height)
        self.thumbnail_render_size = int(self.config_data.thumbnail_size)
        self.thumbnail_resizing = False
        self.thumbnail_hide_suppressed_until = 0.0
        self.thumbnail_rebuild_index = 0
        self.thumbnail_rebuild_timer = QTimer(self)
        self.thumbnail_rebuild_timer.setSingleShot(True)
        self.thumbnail_rebuild_timer.timeout.connect(self.continue_thumbnail_rebuild)
        self.thumbnail_resize_refresh_timer = QTimer(self)
        self.thumbnail_resize_refresh_timer.setSingleShot(True)
        self.thumbnail_resize_refresh_timer.timeout.connect(self.refresh_thumbnail_icons_for_size)
        self.detached_panel_dragging = False
        self.detached_panel_drag_offset = QPoint(0, 0)
        self.profile_stats: dict[str, dict[str, float]] = {}
        self.profile_update_timer = QTimer(self)
        self.profile_update_timer.setSingleShot(True)
        self.profile_update_timer.timeout.connect(self.update_profile_panel)
        self.archive_temp_dir: Path | None = None
        self.retired_archive_temp_dirs: list[Path] = []
        self.archive_display_names: ArchiveDisplayMap = {}
        self.archive_source_path: Path | None = None
        self.archive_disabled_scale_options: tuple[bool, bool] | None = None
        self.process_temp_dir = Path(tempfile.mkdtemp(prefix=TEMP_WORK_PREFIX))
        self.write_temp_lock(self.process_temp_dir)

        self.page_scroll_timer = QTimer(self)
        self.page_scroll_timer.timeout.connect(self._drain_page_steps)
        self.pending_page_steps = 0
        self.prefetch_timer = QTimer(self)
        self.prefetch_timer.setSingleShot(True)
        self.prefetch_timer.timeout.connect(self.schedule_prefetch)
        self.prefetch_generation = 0
        self.prefetching_original_paths: set[Path] = set()
        self.prefetching_processed_keys: set[ProcessingKey] = set()
        self.prefetch_viewer_plan: list[Path] = []
        self.prefetch_engine_plan: list[Path] = []
        self.prefetch_engine_done_paths: set[Path] = set()
        self.pixmap_prefetch_log_accum = 0
        self.side_panel_visible_before_fullscreen = True
        self.before_fullscreen_geometry = QRect()
        self.before_fullscreen_flags = self.windowFlags()
        self.before_fullscreen_state = Qt.WindowNoState
        self.fullscreen_ui_hide_timer = QTimer(self)
        self.fullscreen_ui_hide_timer.setSingleShot(True)
        self.fullscreen_ui_hide_timer.timeout.connect(self.hide_fullscreen_ui_if_idle)

    def _trim_processed_cache(self) -> None:
        while len(self.processed_cache) > self.processed_cache_limit:
            self.processed_cache.popitem(last=False)

    def _init_ui(self) -> None:
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        if APP_ICON_ICO.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_ICO)))
        elif APP_ICON_PNG.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PNG)))

        self.viewer_host = QWidget()
        self.viewer_host.setMouseTracking(True)
        self.viewer_host.installEventFilter(self)
        self.viewer = GLImageView()
        self.viewer.setParent(self.viewer_host)
        self.viewer.pageRequested.connect(self.queue_page_steps)
        self.viewer.firstRequested.connect(self.show_first_image)
        self.viewer.lastRequested.connect(self.show_last_image)
        self.viewer.zoomChanged.connect(self.update_zoom_label)
        self.viewer.splitChanged.connect(self.on_viewer_split_changed)
        self.viewer.fullscreenRequested.connect(self.toggle_fullscreen)
        self.viewer.resetRequested.connect(self.viewer.reset_display_state)
        self.viewer.actualSizeRequested.connect(self.viewer.zoom_to_actual_size)
        self.viewer.actionRequested.connect(self.perform_action)
        self.viewer.emptyAreaClicked.connect(self.open_image_dialog)
        self.viewer.pixmapPrefetchProgress.connect(self.on_pixmap_prefetch_progress)
        self.viewer.installEventFilter(self)
        self.thumbnail_panel = self.build_thumbnail_panel()
        self.thumbnail_panel.setParent(self.viewer_host)
        self.thumbnail_panel.installEventFilter(self)
        self.thumbnail_list.installEventFilter(self)
        self.thumbnail_list.viewport().installEventFilter(self)
        self.restore_side_panel_button = QPushButton("設定を再表示", self.viewer_host)
        self.restore_side_panel_button.clicked.connect(self.show_side_panel)
        self.restore_side_panel_button.hide()

        self.side_panel = self._build_side_panel()
        self.side_panel.installEventFilter(self)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.viewer_host)
        self.splitter.addWidget(self.side_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.splitterMoved.connect(self.on_splitter_moved)
        self.setCentralWidget(self.splitter)

        self._restore_geometry()

    def _init_workers(self) -> None:
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()
        self.prefetch_io_workers = [
            threading.Thread(target=self._prefetch_io_worker_loop, daemon=True)
            for _index in range(2)
        ]
        for worker in self.prefetch_io_workers:
            worker.start()
        worker_count = max(1, min(MAX_THUMBNAIL_WORKER_COUNT, int(self.config_data.thumbnail_worker_count)))
        self.thumbnail_workers = [threading.Thread(target=self._thumbnail_worker_loop, daemon=True) for _ in range(worker_count)]
        for worker in self.thumbnail_workers:
            worker.start()

    def ensure_thumbnail_worker_count(self) -> None:
        target = max(1, min(MAX_THUMBNAIL_WORKER_COUNT, int(self.thumbnail_worker_spin.value())))
        current = len(self.thumbnail_workers)
        if target <= current:
            return
        for _ in range(target - current):
            worker = threading.Thread(target=self._thumbnail_worker_loop, daemon=True)
            self.thumbnail_workers.append(worker)
            worker.start()

    def build_thumbnail_panel(self) -> QWidget:
        panel = QWidget(self.viewer_host)
        panel.setObjectName("thumbnailPanel")
        panel.setAutoFillBackground(True)
        panel.setStyleSheet("#thumbnailPanel { background: palette(window); border-top: 1px solid palette(mid); }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 4, 6, 4)
        self.thumbnail_list = QListWidget(panel)
        self.thumbnail_list.setViewMode(QListView.IconMode)
        self.thumbnail_list.setFlow(QListView.LeftToRight)
        self.thumbnail_list.setWrapping(False)
        self.thumbnail_list.setMovement(QListView.Static)
        self.thumbnail_list.setResizeMode(QListView.Adjust)
        self.thumbnail_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.thumbnail_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumbnail_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.thumbnail_list.setStyleSheet(
            "QListWidget::item:selected { border: 3px solid #2f80ff; background: rgba(47, 128, 255, 70); }"
            "QListWidget::item { margin: 2px; padding: 2px; }"
        )
        self.thumbnail_list.itemClicked.connect(self.on_thumbnail_clicked)
        layout.addWidget(self.thumbnail_list)
        return panel

    def thumbnail_panel_height(self) -> int:
        return self.clamped_thumbnail_height()

    def clamped_thumbnail_height(self, height: int | None = None) -> int:
        value = int(self.thumbnail_height if height is None else height)
        return max(THUMBNAIL_MIN_HEIGHT, min(THUMBNAIL_MAX_HEIGHT, value))

    def thumbnail_icon_size(self, height: int | None = None) -> int:
        panel_height = self.clamped_thumbnail_height(height)
        return max(48, min(256, panel_height - 48))

    def thumbnails_enabled(self) -> bool:
        check = getattr(self, "thumbnail_enabled_check", None)
        return bool(check.isChecked() if check is not None else self.config_data.thumbnail_enabled)

    def thumbnails_pinned(self) -> bool:
        check = getattr(self, "thumbnail_pinned_check", None)
        return bool(check.isChecked() if check is not None else self.config_data.thumbnail_pinned)

    def layout_viewer_host(self) -> None:
        if not hasattr(self, "viewer_host"):
            return
        rect = self.viewer_host.rect()
        if rect.isNull():
            return
        enabled = self.thumbnails_enabled()
        pinned = enabled and self.thumbnails_pinned()
        strip_height = self.thumbnail_panel_height() if enabled else 0
        if pinned:
            viewer_height = max(1, rect.height() - strip_height)
            self.viewer.setGeometry(0, 0, rect.width(), viewer_height)
            self.thumbnail_panel.setGeometry(0, viewer_height, rect.width(), strip_height)
            self.thumbnail_panel.show()
            self.thumbnail_overlay_visible = False
        else:
            self.viewer.setGeometry(rect)
            self.thumbnail_panel.setGeometry(0, max(0, rect.height() - strip_height), rect.width(), strip_height)
            self.thumbnail_panel.setVisible(enabled and self.thumbnail_overlay_visible)
            if self.thumbnail_panel.isVisible():
                self.thumbnail_panel.raise_()
        self.update_thumbnail_metrics()
        self.thumbnail_height = strip_height if enabled else self.thumbnail_height
        if hasattr(self, "restore_side_panel_button"):
            button_width = 140
            button_height = 32
            margin = 12
            self.restore_side_panel_button.setGeometry(rect.width() - button_width - margin, margin, button_width, button_height)
            should_show_restore = bool(
                getattr(self.config_data, "side_panel_detached", False)
                and hasattr(self, "side_panel")
                and not self.side_panel.isVisible()
            )
            self.restore_side_panel_button.setVisible(should_show_restore)

    def show_thumbnail_overlay(self) -> None:
        if not self.thumbnails_enabled() or self.thumbnails_pinned():
            return
        if not self.thumbnail_overlay_visible:
            self.thumbnail_overlay_visible = True
            self.layout_viewer_host()
        self.thumbnail_panel.raise_()

    def hide_thumbnail_overlay(self) -> None:
        if self.thumbnails_pinned() or not self.thumbnail_overlay_visible:
            return
        if self.thumbnail_resizing or time.monotonic() < self.thumbnail_hide_suppressed_until:
            return
        if self.is_cursor_over_thumbnail_panel():
            return
        self.thumbnail_overlay_visible = False
        self.layout_viewer_host()

    def is_cursor_over_thumbnail_panel(self) -> bool:
        if not hasattr(self, "thumbnail_panel") or not self.thumbnail_panel.isVisible():
            return False
        local = self.thumbnail_panel.mapFromGlobal(QCursor.pos())
        return self.thumbnail_panel.rect().adjusted(0, -THUMBNAIL_HIDE_MARGIN, 0, THUMBNAIL_HIDE_MARGIN).contains(local)

    def _build_side_panel(self) -> QWidget:
        root = QWidget()
        root.setMinimumWidth(240)
        root.setAutoFillBackground(True)
        root.setObjectName("sidePanel")
        root.setStyleSheet("#sidePanel { background: palette(window); }")
        layout = QVBoxLayout(root)
        header_widget = QWidget(root)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(QLabel("設定"))
        self.side_panel_position_combo = QComboBox()
        for key, label in SIDE_PANEL_POSITIONS.items():
            self.side_panel_position_combo.addItem(label, key)
        current_position = self.config_data.side_panel_position if self.config_data.side_panel_position in SIDE_PANEL_POSITIONS else "right"
        self.side_panel_position_combo.setCurrentIndex(max(0, self.side_panel_position_combo.findData(current_position)))
        self.side_panel_position_combo.currentIndexChanged.connect(self.on_side_panel_position_changed)
        header.addWidget(self.side_panel_position_combo)
        self.side_panel_detach_check = QCheckBox("分離")
        self.side_panel_detach_check.setChecked(self.config_data.side_panel_detached)
        self.side_panel_detach_check.stateChanged.connect(self.on_side_panel_detached_changed)
        header.addWidget(self.side_panel_detach_check)
        header.addStretch(1)
        self.pin_button = QPushButton("固定")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(self.config_data.side_panel_pinned)
        self.pin_button.setEnabled(not self.config_data.side_panel_detached)
        self.pin_button.toggled.connect(self.on_side_panel_pin_changed)
        header.addWidget(self.pin_button)
        self.side_panel_header = header_widget
        self.side_panel_header.installEventFilter(self)
        layout.addWidget(header_widget)
        self.pin_button.setText("固定中" if self.config_data.side_panel_pinned else "自動表示")

        tabs = QTabWidget()
        self.tabs = tabs
        realcugan_tab = QScrollArea()
        general_tab = QScrollArea()
        keyconfig_tab = QScrollArea()
        realcugan_tab.setWidgetResizable(True)
        general_tab.setWidgetResizable(True)
        keyconfig_tab.setWidgetResizable(True)
        tabs.addTab(realcugan_tab, "エンジン設定")
        tabs.addTab(general_tab, "全般")
        tabs.addTab(keyconfig_tab, "キーコンフィグ")
        tabs.currentChanged.connect(self.on_settings_tab_changed)
        layout.addWidget(tabs)

        realcugan_tab.setWidget(self._build_engine_tab_content())
        general_tab.setWidget(self._build_general_tab_content())
        keyconfig_tab.setWidget(self.build_keyconfig_tab())

        tab_index = {"realcugan": 0, "general": 1, "keyconfig": 2}.get(self.config_data.settings_tab, 0)
        self.tabs.setCurrentIndex(tab_index)
        self.apply_engine_ui()
        QTimer.singleShot(0, self.apply_language)
        return root

    def _build_engine_tab_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        form = QFormLayout()
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(list(ENGINE_LABELS.values()))
        self.engine_combo.setCurrentText(ENGINE_LABELS.get(self.config_data.engine, ENGINE_LABELS[ENGINE_REALCUGAN]))
        self.engine_combo.currentTextChanged.connect(self.on_engine_changed)
        form.addRow("エンジン", self.engine_combo)
        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["2", "3", "4"])
        self.scale_combo.setCurrentText(str(self.config_data.scale))
        self.scale_combo.currentTextChanged.connect(self.on_processing_settings_changed)
        form.addRow("倍率", self.scale_combo)

        self.denoise_combo = QComboBox()
        self.denoise_combo.addItems(["-1", "0", "1", "2", "3"])
        self.denoise_combo.setCurrentText(str(self.config_data.denoise))
        self.denoise_combo.currentTextChanged.connect(self.on_processing_settings_changed)
        form.addRow("ノイズ", self.denoise_combo)
        self.realesrgan_model_combo = QComboBox()
        self.realesrgan_model_combo.addItems(REALESRGAN_MODELS)
        self.realesrgan_model_combo.setCurrentText(self.config_data.realesrgan_model)
        self.realesrgan_model_combo.currentTextChanged.connect(self.on_processing_settings_changed)
        form.addRow("Real-ESRGANモデル", self.realesrgan_model_combo)
        self.tile_spin = QSpinBox()
        self.tile_spin.setRange(0, 16)
        self.tile_spin.setValue(self.config_data.tile)
        self.tile_spin.valueChanged.connect(self.on_processing_settings_changed)
        form.addRow("tile", self.tile_spin)
        layout.addLayout(form)
        self.denoise_help = self.help_label("ノイズ: Real-CUGAN専用。-1 はノイズ除去なし。0/1/2/3 は数値が大きいほど強く除去します。")
        layout.addWidget(self.denoise_help)
        self.realesrgan_model_help = self.help_label("Real-ESRGANはノイズ値を使わず、モデルで画風や復元傾向を選びます。")
        layout.addWidget(self.realesrgan_model_help)
        self.realesrgan_model_detail = self.help_label(
            "realesr-animevideov3: アニメ/イラスト向けの軽量標準モデル。"
            " realesrgan-x4plus: 写真や一般画像向け。"
            " realesrgan-x4plus-anime: アニメ/イラスト向けのx4plus派生モデル。"
            " RAIVではReal-ESRGAN選択中、倍率は4倍固定として処理します。"
        )
        layout.addWidget(self.realesrgan_model_detail)

        layout.addWidget(self.help_label("tile: 0 は自動。小さめの値はGPUメモリ使用量を抑えますが、遅くなることがあります。"))

        form3 = QFormLayout()
        self.realcugan_prefetch_spin = QSpinBox()
        self.realcugan_prefetch_spin.setRange(0, 99999)
        self.realcugan_prefetch_spin.setValue(self.config_data.realcugan_prefetch_count)
        self.realcugan_prefetch_spin.valueChanged.connect(self.on_processing_settings_changed)
        form3.addRow("エンジン先読み", self.realcugan_prefetch_spin)
        self.engine_retry_spin = QSpinBox()
        self.engine_retry_spin.setRange(0, MAX_ENGINE_RETRY_COUNT)
        self.engine_retry_spin.setValue(self.config_data.engine_retry_count)
        self.engine_retry_spin.valueChanged.connect(self.on_processing_settings_changed)
        form3.addRow("エンジン再試行回数", self.engine_retry_spin)
        form3.addRow(self.help_label("選択中の拡大エンジンで処理を先に進める枚数。大きいほど待ち時間を減らせますが、GPU負荷と一時ファイル作成が増えます。"))
        self.skip_tall_check = QCheckBox("縦サイズが閾値以上なら拡大処理しない")
        self.skip_tall_check.setChecked(self.config_data.skip_realcugan_for_tall_images)
        self.skip_tall_check.stateChanged.connect(self.on_processing_settings_changed)
        self.skip_height_spin = QSpinBox()
        self.skip_height_spin.setRange(1, 99999)
        self.skip_height_spin.setValue(self.config_data.skip_realcugan_height_threshold)
        self.skip_height_spin.valueChanged.connect(self.on_processing_settings_changed)
        form3.addRow(self.skip_tall_check)
        form3.addRow("縦サイズ閾値(px)", self.skip_height_spin)
        form3.addRow(self.help_label("モニタ解像度以上の画像をさらに拡大しても表示上の効果は小さく、処理時間とメモリ使用量が増えます。普段使うモニタの縦解像度に合わせる設定が目安です。"))
        layout.addLayout(form3)

        self.save_scale_check = QCheckBox("拡大結果を倍率フォルダに保存")
        self.save_scale_check.setChecked(self.config_data.save_upscaled_to_scale_folder)
        self.save_scale_check.stateChanged.connect(self.on_processing_settings_changed)
        self.use_scale_cache_check = QCheckBox("倍率フォルダがあれば表示に使う")
        self.use_scale_cache_check.setChecked(self.config_data.use_scale_folder_cache)
        self.use_scale_cache_check.stateChanged.connect(self.on_processing_settings_changed)
        layout.addWidget(self.save_scale_check)
        layout.addWidget(self.use_scale_cache_check)
        self.archive_help = self.help_label("アーカイブ表示中は保存先フォルダがないため、倍率フォルダ保存と倍率フォルダ読み込みは無効です。")
        self.archive_help.hide()
        layout.addWidget(self.archive_help)
        rerun_button = QPushButton("再実行")
        rerun_button.clicked.connect(self.force_reprocess)
        layout.addWidget(rerun_button)
        preset_row = QHBoxLayout()
        self.engine_preset_combo = QComboBox()
        self.refresh_engine_preset_combo()
        load_preset_button = QPushButton("プリセット読込")
        load_preset_button.clicked.connect(self.load_selected_engine_preset)
        save_preset_button = QPushButton("現在設定を保存")
        save_preset_button.clicked.connect(self.save_current_engine_preset)
        recommend_button = QPushButton("モデル推奨を適用")
        recommend_button.clicked.connect(self.apply_recommended_model_preset)
        preset_row.addWidget(self.engine_preset_combo, 1)
        preset_row.addWidget(load_preset_button)
        preset_row.addWidget(save_preset_button)
        preset_row.addWidget(recommend_button)
        layout.addLayout(preset_row)
        cancel_button = QPushButton("Cancel processing")
        cancel_button.clicked.connect(self.cancel_processing_jobs)
        layout.addWidget(cancel_button)
        layout.addWidget(self.separator())

        layout.addWidget(QLabel("コマンドテンプレート"))
        self.command_edit = QLineEdit(self.active_command_template())
        self.command_edit.textChanged.connect(self.on_command_template_text_changed)
        layout.addWidget(self.command_edit)
        exe_button = QPushButton("エンジンexeを選択")
        exe_button.clicked.connect(self.choose_engine_exe)
        layout.addWidget(exe_button)
        version_row = QHBoxLayout()
        self.engine_version_label = QLabel("-")
        refresh_version_button = QPushButton("診断")
        refresh_version_button.clicked.connect(self.refresh_engine_version_info)
        version_row.addWidget(self.engine_version_label, 1)
        version_row.addWidget(refresh_version_button)
        form3.addRow("エンジンバージョン", version_row)
        layout.addWidget(self.help_label("使用できる置換: {input} {output} {scale} {denoise} {tile} {model}"))
        layout.addStretch(1)
        self.normalize_form_labels(form, form3)
        self.refresh_engine_version_info()
        return content

    def _build_general_tab_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        self.settings_search_edit = QLineEdit()
        self.settings_search_edit.setPlaceholderText("設定を検索")
        self.settings_search_edit.textChanged.connect(self.on_settings_search_changed)
        layout.addWidget(self.settings_search_edit)

        bookmark_row = QHBoxLayout()
        bookmark_button = QPushButton("ブックマーク切替")
        bookmark_button.clicked.connect(self.toggle_current_bookmark)
        bookmark_next_button = QPushButton("次のブックマーク")
        bookmark_next_button.clicked.connect(self.jump_to_next_bookmark)
        favorite_button = QPushButton("お気に入り切替")
        favorite_button.clicked.connect(self.toggle_current_favorite)
        favorite_next_button = QPushButton("次のお気に入り")
        favorite_next_button.clicked.connect(self.jump_to_next_favorite)
        bookmark_row.addWidget(bookmark_button)
        bookmark_row.addWidget(bookmark_next_button)
        bookmark_row.addWidget(favorite_button)
        bookmark_row.addWidget(favorite_next_button)
        layout.addLayout(bookmark_row)

        self.cleanup_check = QCheckBox("次回起動時に古い一時ファイルを削除")
        self.cleanup_check.setChecked(self.config_data.cleanup_temp_on_start)
        self.cleanup_check.stateChanged.connect(self.on_cleanup_changed)
        layout.addWidget(self.cleanup_check)
        layout.addWidget(self.separator())

        language_form = QFormLayout()
        self.language_combo = QComboBox()
        self.language_combo.addItem("日本語", "ja")
        self.language_combo.addItem("English", "en")
        self.language_combo.setCurrentIndex(0 if self.config_data.ui_language == "ja" else 1)
        self.language_combo.currentIndexChanged.connect(self.on_language_changed)
        self.language_label = QLabel("Language")
        self.language_label.setObjectName("languageLabel")
        language_form.addRow(self.language_label, self.language_combo)
        layout.addLayout(language_form)

        viewer_form = QFormLayout()
        self.viewer_prefetch_spin = QSpinBox()
        self.viewer_prefetch_spin.setRange(0, 99999)
        self.viewer_prefetch_spin.setValue(self.config_data.viewer_prefetch_count)
        self.viewer_prefetch_spin.valueChanged.connect(self.on_viewer_prefetch_changed)
        viewer_form.addRow("ビューアー先読み", self.viewer_prefetch_spin)
        self.thumbnail_worker_spin = QSpinBox()
        self.thumbnail_worker_spin.setRange(1, MAX_THUMBNAIL_WORKER_COUNT)
        self.thumbnail_worker_spin.setValue(self.config_data.thumbnail_worker_count)
        self.thumbnail_worker_spin.valueChanged.connect(self.on_general_settings_changed)
        viewer_form.addRow("サムネイルワーカー数", self.thumbnail_worker_spin)
        self.sort_mode_combo = QComboBox()
        for key, label in SORT_MODES.items():
            self.sort_mode_combo.addItem(label, key)
        sort_index = max(0, self.sort_mode_combo.findData(self.config_data.sort_mode))
        self.sort_mode_combo.setCurrentIndex(sort_index)
        self.sort_mode_combo.currentIndexChanged.connect(self.on_sort_mode_changed)
        viewer_form.addRow("並び順", self.sort_mode_combo)
        self.side_panel_width_spin = QSpinBox()
        self.side_panel_width_spin.setRange(240, 2000)
        self.side_panel_width_spin.setValue(max(240, int(self.config_data.side_panel_width)))
        self.side_panel_width_spin.valueChanged.connect(self.on_side_panel_width_changed)
        viewer_form.addRow("ペインサイズ(px)", self.side_panel_width_spin)
        layout.addLayout(viewer_form)
        layout.addWidget(self.help_label("表示用に画像をメモリへ先読みする枚数。大きいほどページ送りは速くなりますが、メモリ使用量が増えます。"))

        self.cpu_resample_check = QCheckBox("CPUリサンプルキャッシュを使う")
        self.cpu_resample_check.setChecked(self.config_data.cpu_resample_cache_enabled)
        self.cpu_resample_check.stateChanged.connect(self.on_resample_settings_changed)
        layout.addWidget(self.cpu_resample_check)

        resample_form = QFormLayout()
        self.cpu_resample_combo = QComboBox()
        self.cpu_resample_combo.addItems(list(RESAMPLE_ALGORITHMS.values()))
        self.cpu_resample_combo.setCurrentText(RESAMPLE_ALGORITHMS.get(self.config_data.cpu_resample_algorithm, RESAMPLE_ALGORITHMS["lanczos3"]))
        self.cpu_resample_combo.currentTextChanged.connect(self.on_resample_settings_changed)
        self.cpu_resample_combo.setEnabled(self.cpu_resample_check.isChecked())
        resample_form.addRow("表示リサンプル方式", self.cpu_resample_combo)
        layout.addLayout(resample_form)
        layout.addWidget(self.help_label("原寸と異なる表示サイズの画像を、よりきれいに見えるよう作成して保持します。オフにすると標準の高速表示になります。"))
        layout.addWidget(self.help_label("Lanczos3: 精細で標準的。Lanczos4: より鋭いがリンギングが出ることがあります。Bicubic: やや柔らかく自然。Area: 大きく縮小する時に安定し、ジャギーを抑えやすい方式です。"))
        layout.addWidget(self.help_label("Lanczos4はOpenCVがある環境ではLanczos4、ない環境ではLanczos3相当で処理します。"))

        background_form = QFormLayout()
        bg_row = QHBoxLayout()
        self.background_edit = QLineEdit(self.config_data.background_color)
        bg_button = QPushButton("選択")
        bg_button.clicked.connect(self.choose_background_color)
        bg_row.addWidget(bg_button)
        bg_row.addWidget(self.background_edit)
        background_form.addRow("背景色", bg_row)
        self.background_edit.editingFinished.connect(self.on_background_changed)
        layout.addLayout(background_form)

        compare_form = QFormLayout()
        if ENABLE_COMPARE_MODE:
            layout.addWidget(self.separator())
            self.compare_check = QCheckBox("比較モード")
            self.compare_check.setChecked(self.config_data.compare_enabled)
            self.compare_check.stateChanged.connect(self.on_compare_changed)
            layout.addWidget(self.compare_check)
            self.compare_slider = QSlider(Qt.Horizontal)
            self.compare_slider.setRange(0, 1000)
            self.compare_slider.setValue(self.config_data.compare_split)
            self.compare_slider.valueChanged.connect(self.on_compare_changed)
            compare_form.addRow("比較スライダー", self.compare_slider)
            compare_center_button = QPushButton("中央に戻す")
            compare_center_button.clicked.connect(self.reset_compare_split)
            compare_form.addRow("", compare_center_button)
            compare_color_row = QHBoxLayout()
            self.compare_line_edit = QLineEdit(self.config_data.compare_line_color)
            compare_color_button = QPushButton("選択")
            compare_color_button.clicked.connect(self.choose_compare_line_color)
            compare_color_row.addWidget(compare_color_button)
            compare_color_row.addWidget(self.compare_line_edit)
            compare_form.addRow("境界線色", compare_color_row)
            self.compare_line_edit.editingFinished.connect(self.on_compare_changed)
            self.compare_line_width_spin = QSpinBox()
            self.compare_line_width_spin.setRange(1, 20)
            self.compare_line_width_spin.setValue(self.config_data.compare_line_width)
            self.compare_line_width_spin.valueChanged.connect(self.on_compare_changed)
            compare_form.addRow("境界線の太さ(px)", self.compare_line_width_spin)
            layout.addLayout(compare_form)
            self.compare_swap_check = QCheckBox("比較の左右を入れ替える")
            self.compare_swap_check.setChecked(self.config_data.compare_swap_sides)
            self.compare_swap_check.stateChanged.connect(self.on_compare_changed)
            layout.addWidget(self.compare_swap_check)
            self.compare_shift_check = QCheckBox("比較中はShift+ドラッグで境界線を動かす")
            self.compare_shift_check.setChecked(self.config_data.compare_shift_drag_moves_boundary)
            self.compare_shift_check.stateChanged.connect(self.on_compare_changed)
            layout.addWidget(self.compare_shift_check)
            self.compare_diff_highlight_check = QCheckBox("差分ハイライト表示")
            self.compare_diff_highlight_check.setChecked(self.config_data.compare_diff_highlight)
            self.compare_diff_highlight_check.stateChanged.connect(self.on_compare_changed)
            layout.addWidget(self.compare_diff_highlight_check)
            self.compare_diff_threshold_spin = QSpinBox()
            self.compare_diff_threshold_spin.setRange(0, 255)
            self.compare_diff_threshold_spin.setValue(self.config_data.compare_diff_threshold)
            self.compare_diff_threshold_spin.valueChanged.connect(self.on_compare_changed)
            compare_form.addRow("差分しきい値", self.compare_diff_threshold_spin)

        view_form = QFormLayout()
        self.zoom_label = QLabel("ズーム: 100%")
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 500)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self.on_zoom_slider_changed)
        view_form.addRow(self.zoom_label, self.zoom_slider)
        reset_button = QPushButton("表示を中央へリセット")
        reset_button.clicked.connect(self.viewer.reset_display_state)
        view_form.addRow("", reset_button)

        self.page_interval_spin = QSpinBox()
        self.page_interval_spin.setRange(0, 100)
        self.page_interval_spin.setValue(self.config_data.page_scroll_interval_ms)
        self.page_interval_spin.valueChanged.connect(self.on_general_settings_changed)
        view_form.addRow("ページ送り間隔(ms)", self.page_interval_spin)
        self.zoom_precision_spin = QSpinBox()
        self.zoom_precision_spin.setRange(0, 3)
        self.zoom_precision_spin.setValue(self.config_data.zoom_label_precision)
        self.zoom_precision_spin.valueChanged.connect(self.on_general_settings_changed)
        view_form.addRow("Zoom precision", self.zoom_precision_spin)
        layout.addLayout(view_form)
        layout.addWidget(self.help_label("ホイールやキー操作で連続ページ送りする時の間隔。0 は最短です。"))
        page_position_form = QFormLayout()
        self.page_position_slider = QSlider(Qt.Horizontal)
        self.page_position_slider.setRange(0, 0)
        self.page_position_slider.setEnabled(False)
        self.page_position_slider.setInvertedAppearance(self.config_data.invert_page_position_slider)
        self.page_position_slider.valueChanged.connect(self.on_page_position_slider_changed)
        page_position_row = QHBoxLayout()
        self.page_position_count_label = QLabel("0/0")
        self.page_position_count_label.setMinimumWidth(52)
        self.page_position_count_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        page_position_row.addWidget(self.page_position_slider, 1)
        page_position_row.addWidget(self.page_position_count_label)
        page_position_form.addRow("ページ位置", page_position_row)
        jump_row = QHBoxLayout()
        self.page_jump_spin = QSpinBox()
        self.page_jump_spin.setRange(1, 1)
        self.page_jump_spin.setValue(max(1, self.config_data.page_jump_value))
        jump_button = QPushButton("Jump")
        jump_button.clicked.connect(self.on_page_jump_requested)
        jump_row.addWidget(self.page_jump_spin)
        jump_row.addWidget(jump_button)
        page_position_form.addRow("Page jump", jump_row)
        layout.addLayout(page_position_form)
        self.invert_page_position_check = QCheckBox("ページ位置スライダーの左右を入れ替える")
        self.invert_page_position_check.setChecked(self.config_data.invert_page_position_slider)
        self.invert_page_position_check.stateChanged.connect(self.on_page_position_slider_direction_changed)
        layout.addWidget(self.invert_page_position_check)
        layout.addWidget(self.help_label("オンにすると、ページ位置スライダーとサムネイル列の左右方向が連動して入れ替わります。"))
        self.thumbnail_enabled_check = QCheckBox("画面下部にサムネイルを表示する")
        self.thumbnail_enabled_check.setChecked(self.config_data.thumbnail_enabled)
        self.thumbnail_enabled_check.stateChanged.connect(self.on_thumbnail_settings_changed)
        layout.addWidget(self.thumbnail_enabled_check)
        layout.addWidget(self.help_label("オフにするとサムネイル生成処理も停止します。大量の画像を開く時に、初期表示や先読みを軽くできます。"))
        self.thumbnail_pinned_check = QCheckBox("サムネイル列を固定表示する")
        self.thumbnail_pinned_check.setChecked(self.config_data.thumbnail_pinned)
        self.thumbnail_pinned_check.stateChanged.connect(self.on_thumbnail_settings_changed)
        self.thumbnail_pinned_check.setEnabled(self.thumbnail_enabled_check.isChecked())
        layout.addWidget(self.thumbnail_pinned_check)
        self.wrap_page_check = QCheckBox("最後/最初でページ送りしたら反対側へ移動")
        self.wrap_page_check.setChecked(self.config_data.wrap_page_navigation)
        self.wrap_page_check.stateChanged.connect(self.on_general_settings_changed)
        layout.addWidget(self.wrap_page_check)
        self.preserve_view_check = QCheckBox("ページ送り時にズームと表示位置を維持")
        self.preserve_view_check.setChecked(self.config_data.preserve_view_on_page_navigation)
        self.preserve_view_check.stateChanged.connect(self.on_general_settings_changed)
        layout.addWidget(self.preserve_view_check)
        self.spread_mode_check = QCheckBox("見開き表示モード")
        self.spread_mode_check.setChecked(self.config_data.spread_mode_enabled)
        self.spread_mode_check.stateChanged.connect(self.on_spread_mode_changed)
        layout.addWidget(self.spread_mode_check)

        self.exif_auto_orient_check = QCheckBox("EXIF回転情報を表示に反映")
        self.exif_auto_orient_check.setChecked(self.config_data.exif_auto_orient)
        self.exif_auto_orient_check.stateChanged.connect(self.on_exif_orientation_changed)
        layout.addWidget(self.exif_auto_orient_check)

        slideshow_form = QFormLayout()
        self.slideshow_enabled_check = QCheckBox("スライドショー")
        self.slideshow_enabled_check.setChecked(self.config_data.slideshow_enabled)
        self.slideshow_enabled_check.stateChanged.connect(self.on_slideshow_settings_changed)
        self.slideshow_interval_spin = QSpinBox()
        self.slideshow_interval_spin.setRange(1, 30)
        self.slideshow_interval_spin.setValue(self.config_data.slideshow_interval_sec)
        self.slideshow_interval_spin.valueChanged.connect(self.on_slideshow_settings_changed)
        self.slideshow_pause_processing_check = QCheckBox("処理中は自動送りを一時停止")
        self.slideshow_pause_processing_check.setChecked(self.config_data.slideshow_pause_if_processing)
        self.slideshow_pause_processing_check.stateChanged.connect(self.on_slideshow_settings_changed)
        slideshow_form.addRow(self.slideshow_enabled_check)
        slideshow_form.addRow("間隔(秒)", self.slideshow_interval_spin)
        slideshow_form.addRow(self.slideshow_pause_processing_check)
        layout.addLayout(slideshow_form)

        self.horizontal_wheel_check = QCheckBox("マウス横スクロールでページ送り")
        self.horizontal_wheel_check.setChecked(self.config_data.horizontal_wheel_navigation)
        self.horizontal_wheel_check.stateChanged.connect(self.on_general_settings_changed)
        layout.addWidget(self.horizontal_wheel_check)
        self.horizontal_wheel_invert_check = QCheckBox("横スクロールのページ送り方向を反転")
        self.horizontal_wheel_invert_check.setChecked(self.config_data.horizontal_wheel_inverted)
        self.horizontal_wheel_invert_check.stateChanged.connect(self.on_general_settings_changed)
        layout.addWidget(self.horizontal_wheel_invert_check)
        self.hide_cursor_fullscreen_check = QCheckBox("全画面表示時にマウスカーソルを非表示")
        self.hide_cursor_fullscreen_check.setChecked(self.config_data.hide_cursor_in_fullscreen)
        self.hide_cursor_fullscreen_check.stateChanged.connect(self.on_general_settings_changed)
        layout.addWidget(self.hide_cursor_fullscreen_check)
        self.status_label = QLabel("クリックまたはドロップで画像/フォルダ/アーカイブを開く")
        self.status_label.setWordWrap(True)
        layout.addWidget(QLabel("状態"))
        layout.addWidget(self.status_label)
        self.metadata_label = QLabel("-")
        self.metadata_label.setWordWrap(True)
        layout.addWidget(self.metadata_label)
        history_row = QHBoxLayout()
        back_button = QPushButton("History Back")
        back_button.clicked.connect(lambda: self.navigate_history(-1))
        forward_button = QPushButton("History Forward")
        forward_button.clicked.connect(lambda: self.navigate_history(1))
        history_row.addWidget(back_button)
        history_row.addWidget(forward_button)
        layout.addLayout(history_row)

        snapshot_row = QHBoxLayout()
        save_snapshot_button = QPushButton("Save View")
        save_snapshot_button.clicked.connect(self.save_view_snapshot)
        load_snapshot_button = QPushButton("Restore View")
        load_snapshot_button.clicked.connect(self.restore_view_snapshot)
        snapshot_row.addWidget(save_snapshot_button)
        snapshot_row.addWidget(load_snapshot_button)
        layout.addLayout(snapshot_row)

        config_row = QHBoxLayout()
        export_config_button = QPushButton("Export config")
        export_config_button.clicked.connect(self.export_config_file)
        import_config_button = QPushButton("Import config")
        import_config_button.clicked.connect(self.import_config_file)
        config_row.addWidget(export_config_button)
        config_row.addWidget(import_config_button)
        layout.addLayout(config_row)

        recent_row = QHBoxLayout()
        self.recent_dir_combo = QComboBox()
        self.recent_dir_combo.addItems(self.config_data.recent_dirs)
        open_recent_button = QPushButton("Open recent")
        open_recent_button.clicked.connect(self.open_recent_folder)
        recent_row.addWidget(self.recent_dir_combo, 1)
        recent_row.addWidget(open_recent_button)
        layout.addLayout(recent_row)
        layout.addWidget(self.separator())
        self.show_log_check = QCheckBox("ログを表示")
        self.show_log_check.setChecked(self.config_data.show_log_panel)
        self.show_log_check.stateChanged.connect(self.on_log_visibility_changed)
        layout.addWidget(self.show_log_check)
        self.copy_debug_button = QPushButton("デバッグ情報をコピー")
        self.copy_debug_button.clicked.connect(self.on_copy_debug_info)
        layout.addWidget(self.copy_debug_button)
        self.show_diagnostics_button = QPushButton("環境診断を表示")
        self.show_diagnostics_button.clicked.connect(self.on_show_diagnostics)
        layout.addWidget(self.show_diagnostics_button)
        log_form = QFormLayout()
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItem(LOG_LEVEL_INFO, LOG_LEVEL_INFO)
        self.log_level_combo.addItem(LOG_LEVEL_WARN, LOG_LEVEL_WARN)
        self.log_level_combo.addItem(LOG_LEVEL_ERROR, LOG_LEVEL_ERROR)
        active_level = self.config_data.log_level if self.config_data.log_level in LOG_LEVELS else LOG_LEVEL_INFO
        self.log_level_combo.setCurrentText(active_level)
        self.log_level_combo.currentIndexChanged.connect(self.on_log_level_changed)
        log_form.addRow("ログレベル", self.log_level_combo)
        layout.addLayout(log_form)
        self.normalize_form_labels(language_form, viewer_form, resample_form, background_form, compare_form, view_form, page_position_form, log_form)
        self.log_container = QWidget()
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self.prefetch_progress_panel = QWidget()
        progress_layout = QFormLayout(self.prefetch_progress_panel)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.original_prefetch_bar = QProgressBar()
        self.upscale_progress_bar = QProgressBar()
        self.processed_prefetch_bar = QProgressBar()
        self.pixmap_prefetch_bar = QProgressBar()
        for bar in (self.original_prefetch_bar, self.upscale_progress_bar, self.processed_prefetch_bar, self.pixmap_prefetch_bar):
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setTextVisible(True)
        progress_layout.addRow("拡大前メモリ読込", self.original_prefetch_bar)
        progress_layout.addRow("拡大画像生成", self.upscale_progress_bar)
        progress_layout.addRow("拡大後メモリ読込", self.processed_prefetch_bar)
        progress_layout.addRow("表示用QPixmap", self.pixmap_prefetch_bar)
        log_layout.addWidget(self.prefetch_progress_panel)
        self.log_label = QLabel("ログ")
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(160)
        self.log_edit.setSizePolicy(self.log_edit.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
        self.log_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        log_layout.addWidget(self.log_label)
        log_layout.addWidget(self.log_edit)
        layout.addWidget(self.log_container)
        self.show_profile_check = QCheckBox("内部プロファイリングを表示")
        self.show_profile_check.setChecked(self.config_data.show_profile_panel)
        self.show_profile_check.stateChanged.connect(self.on_profile_visibility_changed)
        layout.addWidget(self.show_profile_check)
        self.profile_panel = QLabel()
        self.profile_panel.setWordWrap(True)
        self.profile_panel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.profile_panel)
        layout.addStretch(1)
        self.apply_log_visibility()
        return content

    def build_keyconfig_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addWidget(self.help_label("設定値をクリックすると割当を変更できます。Escを入力すると未割当に戻ります。Spaceは次ページ、Backspaceは前ページとして固定です。"))
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 0)
        grid.addWidget(QLabel("機能"), 0, 0)
        grid.addWidget(QLabel("キーボード"), 0, 1)
        grid.addWidget(QLabel("マウス"), 0, 2)
        self.key_binding_buttons: dict[tuple[str, str], QPushButton] = {}
        for row, (action_id, label) in enumerate(ACTION_DEFS, start=1):
            grid.addWidget(QLabel(label), row, 0)
            for column, kind in ((1, "keyboard"), (2, "mouse")):
                button = QPushButton()
                button.setMinimumWidth(132)
                button.clicked.connect(lambda _checked=False, aid=action_id, k=kind: self.edit_key_binding(aid, k))
                self.key_binding_buttons[(action_id, kind)] = button
                grid.addWidget(button, row, column)
        layout.addLayout(grid)
        reset_button = QPushButton("キーコンフィグを初期値に戻す")
        reset_button.clicked.connect(self.reset_key_bindings)
        layout.addWidget(reset_button)
        layout.addStretch(1)
        self.refresh_keyconfig_buttons()
        return content

    def help_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #666;")
        return label

    def normalize_form_labels(self, *forms: QFormLayout) -> None:
        for form in forms:
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
            form.setHorizontalSpacing(8)
            for row in range(form.rowCount()):
                item = form.itemAt(row, QFormLayout.LabelRole)
                if item is None:
                    continue
                widget = item.widget()
                if widget is not None:
                    widget.setFixedWidth(FORM_LABEL_WIDTH)

    def separator(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.HLine)
        frame.setFrameShadow(QFrame.Sunken)
        return frame

    def ui_language(self) -> str:
        combo = getattr(self, "language_combo", None)
        if combo is not None:
            return combo.currentData() or "ja"
        return self.config_data.ui_language if self.config_data.ui_language in {"ja", "en"} else "ja"

    def tr_ui(self, text: str) -> str:
        return translate_ui_text(text, self.ui_language())

    def apply_language(self) -> None:
        if not hasattr(self, "side_panel"):
            return
        self._translate_widget_tree(self.side_panel)
        if hasattr(self, "tabs"):
            for index in range(self.tabs.count()):
                self.tabs.setTabText(index, self.tr_ui(self.tabs.tabText(index)))
        if hasattr(self, "pin_button"):
            self.pin_button.setText(self.tr_ui("固定中" if self.pin_button.isChecked() else "自動表示"))
        if hasattr(self, "language_label"):
            self.language_label.setText(self.tr_ui("表示言語"))
        if hasattr(self, "restore_side_panel_button"):
            self.restore_side_panel_button.setText(self.tr_ui("設定を再表示"))
        self.update_zoom_label(self.viewer.current_scale() if hasattr(self, "viewer") else 1.0)
        self.update_page_position_slider()
        self.refresh_keyconfig_buttons()
        if hasattr(self, "engine_version_label"):
            self.refresh_engine_version_info()
        if hasattr(self, "metadata_label") and self.image_paths and 0 <= self.current_index < len(self.image_paths):
            path = self.image_paths[self.current_index]
            source = self.load_original(path)
            self.metadata_label.setText(f"{source.width()}x{source.height()} | {path.suffix.lower()} | {path.name}")

    def _translate_widget_tree(self, widget: QWidget) -> None:
        for child in widget.findChildren(QWidget):
            if child.objectName() == "languageLabel":
                continue
            if isinstance(child, QLabel):
                child.setText(self.tr_ui(child.text()))
            elif isinstance(child, QCheckBox):
                child.setText(self.tr_ui(child.text()))
            elif isinstance(child, QPushButton):
                child.setText(self.tr_ui(child.text()))

    def binding_text(self, kind: str, binding: BindingValue | None) -> str:
        text = key_binding_text(binding) if kind == "keyboard" else mouse_binding_text(binding)
        return translate_binding_text(text, self.ui_language())

    def state_text(self, state: str) -> str:
        return translate_state_text(state, self.ui_language())

    def _restore_geometry(self) -> None:
        if not self._restore_window_rect(self.config_data.window_rect):
            self.resize(1200, 760)
            self._center_on_available_screen()
        if self.config_data.window_maximized:
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        self._apply_splitter_panel_width()
        if hasattr(self, "side_panel_detach_check"):
            self.side_panel_detach_check.blockSignals(True)
            self.side_panel_detach_check.setChecked(bool(self.config_data.side_panel_detached))
            self.side_panel_detach_check.blockSignals(False)
        if hasattr(self, "pin_button"):
            self.pin_button.setEnabled(not self.config_data.side_panel_detached)
        if self.config_data.side_panel_detached:
            self.detach_side_panel_for_overlay(visible=self.config_data.side_panel_visible)
            return
        if self.config_data.side_panel_pinned:
            self.config_data.side_panel_visible = True
            self.attach_side_panel_to_splitter(visible=True)
        else:
            self.detach_side_panel_for_overlay(visible=False)

    def _available_virtual_geometry(self) -> QRect:
        available = QRect()
        for screen in QApplication.screens():
            available = screen.availableGeometry() if available.isNull() else available.united(screen.availableGeometry())
        if available.isNull() and QApplication.primaryScreen():
            available = QApplication.primaryScreen().availableGeometry()
        return available

    def _clamp_rect_to_available_geometry(
        self,
        values: list[int] | None,
        minimum_width: int,
        minimum_height: int,
    ) -> tuple[int, int, int, int] | None:
        if not values or len(values) != 4:
            return None
        available = self._available_virtual_geometry()
        if available.isNull():
            return None
        try:
            x, y, width, height = [int(value) for value in values]
        except (TypeError, ValueError):
            return None
        width = max(minimum_width, min(width, max(minimum_width, available.width())))
        height = max(minimum_height, min(height, max(minimum_height, available.height())))
        x = max(available.left(), min(x, available.right() - width + 1))
        y = max(available.top(), min(y, available.bottom() - height + 1))
        return x, y, width, height

    def _restore_window_rect(self, values: list[int] | None) -> bool:
        restored = self._clamp_rect_to_available_geometry(values, 640, 480)
        if restored is None:
            return False
        x, y, width, height = restored
        self.setGeometry(x, y, width, height)
        return True

    def _restore_side_panel_window_rect(self, values: list[int] | None) -> tuple[int, int, int, int] | None:
        return self._clamp_rect_to_available_geometry(values, 240, 260)

    def _center_on_available_screen(self) -> None:
        available = self._available_virtual_geometry()
        if available.isNull():
            return
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _selected_settings_tab(self) -> str:
        return SETTINGS_TABS[max(0, min(len(SETTINGS_TABS) - 1, self.tabs.currentIndex()))]

    def _capture_engine_domain(self) -> EngineConfigDomain:
        return EngineConfigDomain(
            engine=self.current_engine(),
            command_template=self.config_data.realcugan_command_template,
            realcugan_command_template=self.config_data.realcugan_command_template,
            realesrgan_command_template=self.config_data.realesrgan_command_template,
            scale=int(self.scale_combo.currentText()),
            denoise=int(self.denoise_combo.currentText()),
            tile=self.tile_spin.value(),
            engine_retry_count=self.engine_retry_spin.value(),
            realesrgan_model=self.realesrgan_model_combo.currentText(),
            realcugan_prefetch_count=self.realcugan_prefetch_spin.value(),
            save_upscaled_to_scale_folder=(
                self.config_data.save_upscaled_to_scale_folder if self.archive_mode_active() else self.save_scale_check.isChecked()
            ),
            use_scale_folder_cache=(
                self.config_data.use_scale_folder_cache if self.archive_mode_active() else self.use_scale_cache_check.isChecked()
            ),
            skip_realcugan_for_tall_images=self.skip_tall_check.isChecked(),
            skip_realcugan_height_threshold=self.skip_height_spin.value(),
            engine_presets=dict(self.config_data.engine_presets),
        )

    def _capture_viewer_domain(self) -> ViewerConfigDomain:
        return ViewerConfigDomain(
            viewer_prefetch_count=self.viewer_prefetch_spin.value(),
            thumbnail_worker_count=self.thumbnail_worker_spin.value(),
            sort_mode=self.config_data.sort_mode,
            recent_dirs=list(self.config_data.recent_dirs),
            bookmarks=list(self.config_data.bookmarks),
            favorites=list(self.config_data.favorites),
            slideshow_enabled=self.slideshow_enabled_check.isChecked(),
            slideshow_interval_sec=self.slideshow_interval_spin.value(),
            slideshow_pause_if_processing=self.slideshow_pause_processing_check.isChecked(),
            spread_mode_enabled=self.spread_mode_check.isChecked(),
            exif_auto_orient=self.exif_auto_orient_check.isChecked(),
            cpu_resample_cache_enabled=self.cpu_resample_check.isChecked(),
            cpu_resample_algorithm=self.current_resample_algorithm(),
            thumbnail_enabled=self.thumbnail_enabled_check.isChecked(),
            thumbnail_pinned=self.thumbnail_pinned_check.isChecked(),
            thumbnail_size=self.thumbnail_icon_size(),
            thumbnail_height=self.clamped_thumbnail_height(),
            horizontal_wheel_navigation=self.horizontal_wheel_check.isChecked(),
            horizontal_wheel_inverted=self.horizontal_wheel_invert_check.isChecked(),
            wrap_page_navigation=self.wrap_page_check.isChecked(),
            preserve_view_on_page_navigation=self.preserve_view_check.isChecked(),
            invert_page_position_slider=self.invert_page_position_check.isChecked(),
            page_scroll_interval_ms=self.page_interval_spin.value(),
            page_jump_value=self.page_jump_spin.value(),
            max_safe_image_pixels=self.config_data.max_safe_image_pixels,
        )

    def _capture_compare_domain(self) -> CompareConfigDomain:
        if not ENABLE_COMPARE_MODE:
            return CompareConfigDomain()
        compare_check = getattr(self, "compare_check", None)
        compare_slider = getattr(self, "compare_slider", None)
        compare_line_edit = getattr(self, "compare_line_edit", None)
        compare_line_width_spin = getattr(self, "compare_line_width_spin", None)
        compare_swap_check = getattr(self, "compare_swap_check", None)
        compare_shift_check = getattr(self, "compare_shift_check", None)
        compare_diff_highlight_check = getattr(self, "compare_diff_highlight_check", None)
        compare_diff_threshold_spin = getattr(self, "compare_diff_threshold_spin", None)
        return CompareConfigDomain(
            compare_enabled=bool(compare_check.isChecked()) if compare_check is not None else False,
            compare_split=int(compare_slider.value()) if compare_slider is not None else 500,
            compare_line_color=(compare_line_edit.text().strip() if compare_line_edit is not None else "") or "#ffffff",
            compare_line_width=int(compare_line_width_spin.value()) if compare_line_width_spin is not None else 2,
            compare_swap_sides=bool(compare_swap_check.isChecked()) if compare_swap_check is not None else False,
            compare_shift_drag_moves_boundary=bool(compare_shift_check.isChecked()) if compare_shift_check is not None else False,
            compare_diff_highlight=bool(compare_diff_highlight_check.isChecked()) if compare_diff_highlight_check is not None else False,
            compare_diff_threshold=int(compare_diff_threshold_spin.value()) if compare_diff_threshold_spin is not None else 24,
        )

    def _capture_ui_domain(self) -> UiConfigDomain:
        window_rect = self.config_data.window_rect
        window_maximized = self.config_data.window_maximized
        if not self.is_app_fullscreen():
            rect = self.normalGeometry() if self.isMaximized() else self.geometry()
            if rect.isValid():
                window_rect = [rect.x(), rect.y(), rect.width(), rect.height()]
                window_maximized = self.isMaximized()

        side_panel = getattr(self, "side_panel", None)
        pin_button = getattr(self, "pin_button", None)
        detach_check = getattr(self, "side_panel_detach_check", None)
        position_combo = getattr(self, "side_panel_position_combo", None)
        side_panel_visible = (
            self.side_panel_visible_before_fullscreen
            if self.is_app_fullscreen()
            else side_panel.isVisible() if side_panel is not None else self.config_data.side_panel_visible
        )
        side_panel_pinned = pin_button.isChecked() if pin_button is not None else self.config_data.side_panel_pinned
        side_panel_detached = detach_check.isChecked() if detach_check is not None else self.config_data.side_panel_detached
        position = position_combo.currentData() if position_combo is not None else self.config_data.side_panel_position
        side_panel_position = position if position in SIDE_PANEL_POSITIONS else "right"
        side_panel_window_rect = self.config_data.side_panel_window_rect
        side_panel_width = self.config_data.side_panel_width
        if side_panel is not None:
            side_panel_width = int(self.side_panel_width)
            if side_panel_detached:
                rect = side_panel.geometry()
                side_panel_window_rect = [rect.x(), rect.y(), rect.width(), rect.height()]

        splitter_sizes = self.config_data.splitter_sizes
        splitter = getattr(self, "splitter", None)
        if splitter is not None and not self.side_panel_overlay:
            sizes = self.splitter.sizes()
            side_index = self.splitter_side_panel_index() if hasattr(self, "splitter_side_panel_index") else 1
            if len(sizes) >= 2 and sizes[side_index] >= 80:
                splitter_sizes = sizes

        return UiConfigDomain(
            background_color=self.background_edit.text().strip() or DEFAULT_BACKGROUND_COLOR,
            zoom_label_precision=self.zoom_precision_spin.value(),
            hide_cursor_in_fullscreen=self.hide_cursor_fullscreen_check.isChecked(),
            show_log_panel=self.show_log_check.isChecked(),
            log_level=self.log_level(),
            show_profile_panel=self.show_profile_check.isChecked(),
            ui_language=(self.language_combo.currentData() or "ja") if hasattr(self, "language_combo") else self.config_data.ui_language,
            arrow_right_next=self.config_data.arrow_right_next,
            key_bindings=normalize_key_bindings(self.config_data.key_bindings),
            cleanup_temp_on_start=self.cleanup_check.isChecked(),
            settings_tab=self._selected_settings_tab(),
            window_rect=window_rect,
            window_maximized=window_maximized,
            window_geometry="",
            side_panel_visible=side_panel_visible,
            side_panel_pinned=side_panel_pinned,
            side_panel_width=side_panel_width,
            side_panel_position=side_panel_position,
            side_panel_detached=side_panel_detached,
            side_panel_window_rect=side_panel_window_rect,
            splitter_sizes=splitter_sizes,
            last_dir=self.config_data.last_dir,
        )

    def persist_config(self, log: bool = False) -> None:
        if getattr(self, "initializing", False):
            return
        self.save_active_command_template()
        self.config_data.apply_domains(
            engine=self._capture_engine_domain(),
            viewer=self._capture_viewer_domain(),
            compare=self._capture_compare_domain(),
            ui=self._capture_ui_domain(),
        )
        save_config(self.config_data)
        if log:
            self.append_log(f"Saved settings: {CONFIG_PATH}")

    def _apply_settings_to_viewer(self) -> None:
        self.viewer.set_background(self.config_data.background_color)
        self.viewer.set_resample_options(self.config_data.cpu_resample_cache_enabled, self.config_data.cpu_resample_algorithm)
        self.viewer.set_key_bindings(self.config_data.key_bindings)
        self.auto_tune_pixmap_cache_limit()
        self.viewer.set_horizontal_wheel_options(
            self.config_data.horizontal_wheel_navigation,
            self.config_data.horizontal_wheel_inverted,
        )
        self.on_slideshow_settings_changed()
        self.update_thumbnail_metrics()
        self.layout_viewer_host()
        self.on_compare_changed()

    def current_resample_algorithm(self) -> str:
        label = self.cpu_resample_combo.currentText() if hasattr(self, "cpu_resample_combo") else RESAMPLE_ALGORITHMS["lanczos3"]
        for key, value in RESAMPLE_ALGORITHMS.items():
            if label == value:
                return key
        return "lanczos3"

    def refresh_keyconfig_buttons(self) -> None:
        buttons = getattr(self, "key_binding_buttons", {})
        self.duplicate_keyboard_bindings = duplicate_binding_signatures(self.config_data.key_bindings, "keyboard")
        keyboard_duplicates = self.duplicate_keyboard_bindings
        mouse_duplicates = duplicate_binding_signatures(self.config_data.key_bindings, "mouse")
        for action_id, _label in ACTION_DEFS:
            bindings = self.config_data.key_bindings.get(action_id, {"keyboard": None, "mouse": None})
            keyboard_button = buttons.get((action_id, "keyboard"))
            mouse_button = buttons.get((action_id, "mouse"))
            if keyboard_button is not None:
                binding = bindings.get("keyboard")
                duplicate = keyboard_signature(binding) in keyboard_duplicates
                keyboard_button.setText((("! Duplicate: " if self.ui_language() == "en" else "! 重複: ") if duplicate else "") + self.binding_text("keyboard", binding))
                keyboard_button.setStyleSheet("background-color: #7a2020; color: white; border: 2px solid #ffcc66;" if duplicate else "")
                keyboard_button.setToolTip(self.tr_ui("重複しているため、この割当は無効です。キーを再設定してください。") if duplicate else "")
            if mouse_button is not None:
                binding = bindings.get("mouse")
                duplicate = mouse_signature(binding) in mouse_duplicates
                mouse_button.setText((("! Duplicate: " if self.ui_language() == "en" else "! 重複: ") if duplicate else "") + self.binding_text("mouse", binding))
                mouse_button.setStyleSheet("background-color: #7a2020; color: white; border: 2px solid #ffcc66;" if duplicate else "")
                mouse_button.setToolTip(self.tr_ui("重複しているため、この割当は無効です。キーを再設定してください。") if duplicate else "")

    def edit_key_binding(self, action_id: str, kind: str) -> None:
        bindings = self.config_data.key_bindings.setdefault(action_id, {"keyboard": None, "mouse": None})
        action_label = dict(ACTION_DEFS).get(action_id, action_id)
        action_label = self.tr_ui(action_label)
        title = f"{action_label} - {self.tr_ui('キーボード' if kind == 'keyboard' else 'マウス')}"
        dialog = KeyBindingDialog(self, title, kind, bindings.get(kind))
        if dialog.exec() == QDialog.Accepted:
            bindings[kind] = dialog.binding
            self.config_data.key_bindings = normalize_key_bindings(self.config_data.key_bindings)
            self.viewer.set_key_bindings(self.config_data.key_bindings)
            self.refresh_keyconfig_buttons()
            self.persist_config()

    def reset_key_bindings(self) -> None:
        self.config_data.key_bindings = default_key_bindings()
        self.viewer.set_key_bindings(self.config_data.key_bindings)
        self.refresh_keyconfig_buttons()
        self.persist_config()

    def update_thumbnail_metrics(self) -> None:
        if not hasattr(self, "thumbnail_list"):
            return
        size = self.thumbnail_icon_size()
        size_changed = size != getattr(self, "thumbnail_render_size", size)
        self.thumbnail_render_size = size
        self.config_data.thumbnail_size = size
        self.thumbnail_list.setIconSize(QSize(size, size))
        self.thumbnail_list.setGridSize(QSize(size + 28, size + 34))
        self.thumbnail_list.setFixedHeight(max(THUMBNAIL_MIN_HEIGHT - 8, self.thumbnail_panel_height() - 8))
        self.thumbnail_list.setLayoutDirection(Qt.RightToLeft if self.invert_page_position_check.isChecked() else Qt.LeftToRight)
        if size_changed and self.thumbnail_items and self.thumbnails_enabled():
            self.thumbnail_resize_refresh_timer.start(120 if self.thumbnail_resizing else 1)

    def refresh_thumbnail_icons_for_size(self) -> None:
        if not self.thumbnails_enabled() or not self.thumbnail_items:
            return
        self.thumbnail_generation += 1
        self.clear_thumbnail_queue()
        self.thumbnail_ready_indexes.clear()
        for item in self.thumbnail_items:
            if item is not None:
                item.setIcon(QIcon())
        self.schedule_thumbnail_prefetch()

    def clear_thumbnail_queue(self) -> None:
        with self.thumbnail_queue.mutex:
            self.thumbnail_queue.queue.clear()
        self.thumbnail_pending.clear()

    def rebuild_thumbnail_items(self) -> None:
        if not hasattr(self, "thumbnail_list"):
            return
        self.thumbnail_generation += 1
        self.thumbnail_rebuild_timer.stop()
        self.clear_thumbnail_queue()
        self.thumbnail_ready_indexes.clear()
        self.thumbnail_list.clear()
        self.thumbnail_items = []
        if not self.thumbnails_enabled() or not self.image_paths:
            self.layout_viewer_host()
            return
        self.update_thumbnail_metrics()
        self.thumbnail_items = [None] * len(self.image_paths)
        self.thumbnail_rebuild_index = 0
        self.continue_thumbnail_rebuild()
        self.schedule_thumbnail_prefetch()
        self.layout_viewer_host()

    def continue_thumbnail_rebuild(self) -> None:
        if not self.thumbnails_enabled() or not self.image_paths:
            return
        started = time.perf_counter()
        batch = 0
        while self.thumbnail_rebuild_index < len(self.image_paths) and batch < 160:
            index = self.thumbnail_rebuild_index
            path = self.image_paths[index]
            item = QListWidgetItem(str(index + 1))
            item.setData(Qt.UserRole, index)
            item.setToolTip(self.display_name(path))
            self.thumbnail_list.addItem(item)
            self.thumbnail_items[index] = item
            self.thumbnail_rebuild_index += 1
            batch += 1
        self.update_thumbnail_selection(scroll=False, schedule=False)
        self.record_profile("サムネイル項目生成(UI)", (time.perf_counter() - started) * 1000)
        if self.thumbnail_rebuild_index < len(self.image_paths):
            self.thumbnail_rebuild_timer.start(1)

    def schedule_thumbnail_prefetch(self) -> None:
        if not self.thumbnails_enabled() or not self.image_paths:
            return
        self.thumbnail_generation += 1
        self.clear_thumbnail_queue()
        current = max(0, self.current_index)
        limit = min(len(self.image_paths), max(80, self.viewer_prefetch_spin.value() * 2 + 20))
        ordered: list[int] = []
        # Prioritize thumbnails currently visible in the strip to make scrolling feel immediate.
        for item in self.thumbnail_list.findItems("*", Qt.MatchWildcard):
            rect = self.thumbnail_list.visualItemRect(item)
            if rect.isValid() and self.thumbnail_list.viewport().rect().intersects(rect):
                index = item.data(Qt.UserRole)
                if isinstance(index, int) and 0 <= index < len(self.image_paths) and index not in ordered:
                    ordered.append(index)
                    if len(ordered) >= limit:
                        break
        for distance in range(len(self.image_paths)):
            candidates = [current] if distance == 0 else [current + distance, current - distance]
            for index in candidates:
                if 0 <= index < len(self.image_paths) and index not in ordered:
                    ordered.append(index)
                    if len(ordered) >= limit:
                        break
            if len(ordered) >= limit:
                break
        for index in ordered:
            if index in self.thumbnail_ready_indexes:
                continue
            with self.thumbnail_lock:
                self.thumbnail_sequence += 1
                sequence = self.thumbnail_sequence
            priority = abs(index - current)
            self.thumbnail_pending.add(index)
            self.thumbnail_queue.put((priority, sequence, self.thumbnail_generation, index, str(self.image_paths[index])))

    def _thumbnail_worker_loop(self) -> None:
        while True:
            priority, sequence, generation, index, path_text = self.thumbnail_queue.get()
            if getattr(self, "closing", False):
                return
            if generation != self.thumbnail_generation:
                continue
            started = time.perf_counter()
            image = QImage(path_text)
            size = int(self.config_data.thumbnail_size)
            if not image.isNull():
                image = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.signals.profile_event.emit("サムネイル生成", (time.perf_counter() - started) * 1000)
            self.signals.thumbnail_done.emit(generation, index, image)

    def on_thumbnail_done(self, generation: int, index: int, image: QImage) -> None:
        self.thumbnail_pending.discard(index)
        if generation != self.thumbnail_generation or index < 0 or index >= len(self.thumbnail_items):
            return
        item = self.thumbnail_items[index]
        if item is None:
            return
        if not image.isNull():
            started = time.perf_counter()
            item.setIcon(QIcon(QPixmap.fromImage(image)))
            self.record_profile("サムネイル反映(UI)", (time.perf_counter() - started) * 1000)
        self.thumbnail_ready_indexes.add(index)

    def on_thumbnail_clicked(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.UserRole)
        if not isinstance(index, int) or index < 0 or index >= len(self.image_paths) or index == self.current_index:
            return
        scroll_bar = self.thumbnail_list.horizontalScrollBar()
        scroll_value = scroll_bar.value()
        self.last_navigation_step = 1 if index > self.current_index else -1
        self.current_index = index
        self.display_current_image(preserve_view=self.preserve_view_check.isChecked(), navigation=True, scroll_thumbnail=False)
        scroll_bar.setValue(scroll_value)

    def update_thumbnail_selection(self, scroll: bool = True, schedule: bool = True) -> None:
        if not hasattr(self, "thumbnail_list") or self.current_index < 0 or self.current_index >= len(self.thumbnail_items):
            return
        item = self.thumbnail_items[self.current_index]
        if item is None:
            return
        scroll_bar = self.thumbnail_list.horizontalScrollBar()
        scroll_value = scroll_bar.value() if not scroll else None
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.setCurrentItem(item)
        self.thumbnail_list.blockSignals(False)
        if scroll:
            self.thumbnail_list.scrollToItem(item, QAbstractItemView.EnsureVisible)
        elif scroll_value is not None:
            scroll_bar.setValue(scroll_value)
            QTimer.singleShot(0, lambda bar=scroll_bar, value=scroll_value: bar.setValue(value))
        if schedule and self.thumbnails_enabled():
            self.schedule_thumbnail_prefetch()

    def on_thumbnail_settings_changed(self) -> None:
        enabled = self.thumbnail_enabled_check.isChecked()
        self.thumbnail_pinned_check.setEnabled(enabled)
        self.config_data.thumbnail_enabled = enabled
        self.config_data.thumbnail_pinned = self.thumbnail_pinned_check.isChecked()
        self.thumbnail_height = self.clamped_thumbnail_height()
        self.config_data.thumbnail_size = self.thumbnail_icon_size()
        self.update_thumbnail_metrics()
        if enabled:
            self.rebuild_thumbnail_items()
        else:
            self.thumbnail_generation += 1
            self.thumbnail_rebuild_timer.stop()
            self.clear_thumbnail_queue()
            self.thumbnail_list.clear()
            self.thumbnail_items.clear()
            self.thumbnail_ready_indexes.clear()
        self.layout_viewer_host()
        self.persist_config()

    def update_page_position_slider(self) -> None:
        slider = getattr(self, "page_position_slider", None)
        if slider is None:
            return
        label = getattr(self, "page_position_count_label", None)
        slider.blockSignals(True)
        if self.image_paths and self.current_index >= 0:
            slider.setEnabled(True)
            total = len(self.image_paths)
            if slider.minimum() != 1 or slider.maximum() != total:
                slider.setRange(1, total)
            value = self.current_index + 1
            if slider.value() != value:
                slider.setValue(value)
            if label is not None:
                label.setText(f"{value}/{total}")
            if hasattr(self, "page_jump_spin"):
                self.page_jump_spin.setRange(1, total)
                if self.page_jump_spin.value() > total:
                    self.page_jump_spin.setValue(total)
        else:
            if slider.value() != 0:
                slider.setValue(0)
            if slider.minimum() != 0 or slider.maximum() != 0:
                slider.setRange(0, 0)
            slider.setEnabled(False)
            if label is not None:
                label.setText("0/0")
            if hasattr(self, "page_jump_spin"):
                self.page_jump_spin.setRange(1, 1)
        slider.blockSignals(False)

    def on_page_position_slider_changed(self, value: int) -> None:
        if not self.image_paths or value <= 0:
            return
        index = max(0, min(len(self.image_paths) - 1, value - 1))
        if index == self.current_index:
            return
        self.last_navigation_step = 1 if index > self.current_index else -1
        self.current_index = index
        self.display_current_image(preserve_view=self.preserve_view_check.isChecked(), navigation=True)

    def on_page_jump_requested(self) -> None:
        if not self.image_paths:
            return
        target = max(1, min(len(self.image_paths), self.page_jump_spin.value()))
        self.page_position_slider.setValue(target)
        self.config_data.page_jump_value = target
        self.persist_config()

    def on_page_position_slider_direction_changed(self) -> None:
        self.page_position_slider.setInvertedAppearance(self.invert_page_position_check.isChecked())
        self.update_thumbnail_metrics()
        self.persist_config()

    def current_engine(self) -> str:
        label = self.engine_combo.currentText() if hasattr(self, "engine_combo") else ENGINE_LABELS[ENGINE_REALCUGAN]
        for engine, engine_label in ENGINE_LABELS.items():
            if label == engine_label:
                return engine
        return ENGINE_REALCUGAN

    def default_template_for_engine(self, engine: str) -> str:
        return DEFAULT_REALESRGAN_TEMPLATE if engine == ENGINE_REALESRGAN else DEFAULT_REALCUGAN_TEMPLATE

    def active_command_template(self) -> str:
        return self.config_data.realesrgan_command_template if self.current_engine() == ENGINE_REALESRGAN else self.config_data.realcugan_command_template

    def executable_from_template(self, command_template: str) -> Path | None:
        stripped = command_template.strip()
        if not stripped:
            return None
        if stripped.startswith('"'):
            end = stripped.find('"', 1)
            token = stripped[1:end] if end > 1 else ""
        else:
            token = stripped.split(maxsplit=1)[0]
        if not token:
            return None
        candidate = Path(os.path.expandvars(token))
        if candidate.is_absolute() and candidate.is_file():
            return candidate
        local = APP_DIR / candidate
        if local.is_file():
            return local
        found = shutil.which(token)
        return Path(found) if found else None

    def detect_engine_version(self, engine: str) -> str:
        template = self.config_data.realesrgan_command_template if engine == ENGINE_REALESRGAN else self.config_data.realcugan_command_template
        exe_path = self.executable_from_template(template)
        if exe_path is None or not exe_path.exists():
            return "not found"
        for flag in ("--version", "-V", "-v", "-h"):
            try:
                 completed = subprocess.run(
                     [str(exe_path), flag],
                     stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT,
                     text=True,
                     encoding="utf-8",
                     errors="replace",
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     timeout=6,
                     check=False,
                 )
            except Exception:
                continue
            lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            if lines:
                return lines[0][:120]
        return f"found: {exe_path.name}"

    def refresh_engine_version_info(self) -> None:
        if not hasattr(self, "engine_version_label"):
            return
        engine = self.current_engine()
        version_text = self.detect_engine_version(engine)
        self.engine_version_label.setText(version_text)

    def engine_label(self) -> str:
        return ENGINE_LABELS.get(self.current_engine(), ENGINE_LABELS[ENGINE_REALCUGAN])

    def effective_scale(self) -> int:
        return REALESRGAN_FIXED_SCALE if self.current_engine() == ENGINE_REALESRGAN else int(self.scale_combo.currentText())

    def save_active_command_template(self) -> None:
        if not hasattr(self, "command_edit"):
            return
        text = self.command_edit.text().strip() or self.default_template_for_engine(self.current_engine())
        if self.current_engine() == ENGINE_REALESRGAN:
            self.config_data.realesrgan_command_template = text
        else:
            self.config_data.realcugan_command_template = text

    def on_command_template_text_changed(self, text: str) -> None:
        template = text.strip() or self.default_template_for_engine(self.current_engine())
        if self.current_engine() == ENGINE_REALESRGAN:
            self.config_data.realesrgan_command_template = template
        else:
            self.config_data.realcugan_command_template = template

    def apply_engine_ui(self) -> None:
        if not hasattr(self, "engine_combo"):
            return
        engine = self.current_engine()
        self.scale_combo.setEnabled(engine == ENGINE_REALCUGAN)
        self.denoise_combo.setEnabled(engine == ENGINE_REALCUGAN)
        self.denoise_help.setEnabled(engine == ENGINE_REALCUGAN)
        self.realesrgan_model_combo.setEnabled(engine == ENGINE_REALESRGAN)
        self.realesrgan_model_help.setEnabled(engine == ENGINE_REALESRGAN)
        self.realesrgan_model_detail.setEnabled(engine == ENGINE_REALESRGAN)
        self.command_edit.blockSignals(True)
        self.command_edit.setText(self.active_command_template())
        self.command_edit.blockSignals(False)

    def append_log(self, text: str) -> None:
        self.append_log_with_level(text, LOG_LEVEL_INFO)

    def log_level(self) -> str:
        combo = getattr(self, "log_level_combo", None)
        if combo is not None:
            level = combo.currentData() or combo.currentText()
            if level in LOG_LEVELS:
                return level
        if self.config_data.log_level in LOG_LEVELS:
            return self.config_data.log_level
        return LOG_LEVEL_INFO

    def should_log(self, level: str) -> bool:
        return can_emit_log(level, self.log_level())

    def append_log_with_level(self, text: str, level: str = LOG_LEVEL_INFO) -> None:
        if not self.should_log(level):
            return
        self.log_edit.append(text)

    def append_log_if_visible(self, text: str) -> None:
        if getattr(self, "closing", False):
            return
        if self.show_log_panel:
            self.append_log_with_level(text, LOG_LEVEL_INFO)

    def run_startup_self_check(self) -> None:
        issues: list[tuple[str, str]] = list(self.startup_messages)
        self.startup_messages.clear()
        if not BUNDLED_REALCUGAN_EXE.exists():
            issues.append((LOG_LEVEL_WARN, f"Bundled Real-CUGAN executable not found: {BUNDLED_REALCUGAN_EXE}"))
        if not BUNDLED_REALESRGAN_EXE.exists():
            issues.append((LOG_LEVEL_WARN, f"Bundled Real-ESRGAN executable not found: {BUNDLED_REALESRGAN_EXE}"))
        if not command_executable_exists(self.config_data.realcugan_command_template):
            issues.append((LOG_LEVEL_WARN, "Real-CUGAN command template is not executable. Check engine path settings."))
        if not command_executable_exists(self.config_data.realesrgan_command_template):
            issues.append((LOG_LEVEL_WARN, "Real-ESRGAN command template is not executable. Check engine path settings."))
        if py7zr is None:
            issues.append((LOG_LEVEL_WARN, "py7zr is not available. 7z/CB7 extraction falls back to external 7z command."))
        if rarfile is None and self.find_7z() is None:
            issues.append((LOG_LEVEL_WARN, "rarfile and external 7z are unavailable. RAR/CBR extraction will not work."))
        if cv2 is None:
            issues.append((LOG_LEVEL_WARN, "OpenCV is not available. Lanczos4 falls back to Lanczos3-equivalent behavior."))

        self.append_log_with_level("Startup self-check completed.", LOG_LEVEL_INFO)
        for level, message in issues:
            self.append_log_with_level(message, level)
        if issues:
            visible_text = [message for level, message in issues if LOG_LEVEL_RANK.get(level, 0) >= LOG_LEVEL_RANK.get(LOG_LEVEL_WARN, 1)]
            if visible_text:
                self.status_label.setText(visible_text[-1])

    def record_profile(self, name: str, elapsed_ms: float) -> None:
        if getattr(self, "closing", False):
            return
        if elapsed_ms < 0:
            return
        stats = self.profile_stats.setdefault(name, {"count": 0.0, "total": 0.0, "last": 0.0, "max": 0.0})
        stats["count"] += 1.0
        stats["total"] += float(elapsed_ms)
        stats["last"] = float(elapsed_ms)
        stats["max"] = max(stats["max"], float(elapsed_ms))
        profile_check = getattr(self, "show_profile_check", None)
        if profile_check is not None and profile_check.isChecked() and not self.profile_update_timer.isActive():
            self.profile_update_timer.start(PROFILE_UPDATE_INTERVAL_MS)

    def update_profile_panel(self) -> None:
        if not hasattr(self, "profile_panel"):
            return
        profile_check = getattr(self, "show_profile_check", None)
        if profile_check is None or not profile_check.isChecked():
            self.profile_panel.hide()
            return
        lines = []
        for name, stats in sorted(self.profile_stats.items()):
            count = max(1.0, stats["count"])
            avg = stats["total"] / count
            lines.append(f"{name}: last {stats['last']:.1f} ms / avg {avg:.1f} ms / max {stats['max']:.1f} ms")
        empty = "Profile: no measurements yet" if self.ui_language() == "en" else "プロファイル: まだ計測値がありません"
        self.profile_panel.setText("\n".join(lines[-8:]) if lines else empty)
        self.profile_panel.show()

    def set_progress_bar(self, bar: QProgressBar, value: int, total: int, label: str) -> None:
        if not self.show_log_panel:
            return
        if getattr(self, "closing", False):
            return
        total = max(0, int(total))
        value = max(0, min(int(value), total))
        if total <= 0:
            bar.setRange(0, 1)
            bar.setValue(0)
            bar.setFormat("0/0")
            return
        bar.setRange(0, total)
        bar.setValue(value)
        bar.setFormat(f"{value}/{total}")

    def update_prefetch_progress_bars(self, viewer_plan: list[Path] | None = None, engine_plan: list[Path] | None = None) -> None:
        if not self.show_log_panel:
            return
        engine_plan = engine_plan if engine_plan is not None else self.prefetch_engine_plan
        original_done = len(self.original_cache)
        original_pending = sum(1 for path in self.prefetching_original_paths if path not in self.original_cache)
        original_total = original_done + original_pending
        self.set_progress_bar(self.original_prefetch_bar, original_done, original_total, "拡大前メモリ読込")

        engine_total = len(engine_plan)
        engine_done = sum(1 for path in engine_plan if self.normalized_path(path) in self.prefetch_engine_done_paths)
        self.set_progress_bar(self.upscale_progress_bar, engine_done, engine_total, "拡大画像生成")

        processed_done = len(self.processed_cache)
        processed_pending = sum(1 for key in self.prefetching_processed_keys if key not in self.processed_cache)
        processed_total = processed_done + processed_pending
        self.set_progress_bar(self.processed_prefetch_bar, processed_done, processed_total, "拡大後メモリ読込")

        pixmap_done = len(self.viewer.pixmap_cache)
        pixmap_total = pixmap_done + len(self.viewer.pixmap_prefetch_keys)
        self.set_progress_bar(self.pixmap_prefetch_bar, pixmap_done, pixmap_total, "表示用QPixmap")

    def pixmap_progress_key(self, kind: str, path: Path) -> tuple:
        return (
            kind,
            self.normalized_path_text(path),
            self.current_engine(),
            self.effective_scale(),
            int(self.denoise_combo.currentText()) if self.current_engine() == ENGINE_REALCUGAN else 0,
            self.tile_spin.value(),
            self.realesrgan_model_combo.currentText() if self.current_engine() == ENGINE_REALESRGAN else "",
            self.viewer.display_rotation % 360,
            self.viewer.display_flip_horizontal,
            self.viewer.display_flip_vertical,
        )

    def on_pixmap_prefetch_progress(self, warmed: int, remaining: int, cache_count: int, elapsed_ms: float) -> None:
        self.record_profile("QPixmap生成(UI)", elapsed_ms)
        if not self.show_log_panel:
            return
        self.pixmap_prefetch_log_accum += warmed
        self.update_prefetch_progress_bars()
        if remaining == 0 or self.pixmap_prefetch_log_accum >= 25:
            self.append_log(
                f"Pixmap prefetch: warmed +{self.pixmap_prefetch_log_accum}, remaining={remaining}, pixmaps={cache_count}"
            )
            self.pixmap_prefetch_log_accum = 0

    def apply_log_visibility(self) -> None:
        log_visible = bool(self.show_log_panel)
        profile_visible = bool(self.show_profile_check.isChecked())
        self.log_container.setVisible(log_visible)
        self.log_container.setMaximumHeight(16777215 if log_visible else 0)
        self.log_container.setMinimumHeight(0)
        if hasattr(self, "profile_panel"):
            self.profile_panel.setVisible(profile_visible)
        if hasattr(self, "prefetch_progress_panel"):
            self.prefetch_progress_panel.setVisible(log_visible)
        if hasattr(self, "log_label"):
            self.log_label.setVisible(log_visible)
        if hasattr(self, "log_edit"):
            self.log_edit.setVisible(log_visible)
        if profile_visible:
            self.update_profile_panel()
        if log_visible:
            self.update_prefetch_progress_bars()
            if self.image_paths:
                self.request_schedule_prefetch(0)

    def on_log_visibility_changed(self) -> None:
        self.show_log_panel = self.show_log_check.isChecked()
        self.apply_log_visibility()
        self.persist_config()

    def on_profile_visibility_changed(self) -> None:
        self.update_profile_panel()
        self.apply_log_visibility()
        self.persist_config()

    def on_log_level_changed(self) -> None:
        self.config_data.log_level = self.log_level()
        self.persist_config()

    def open_path(self, path: Path) -> None:
        path = path.resolve()
        if path.is_file() and path.suffix.lower() == ".pdf":
            self.open_pdf(path)
            return
        if path.is_file() and path.suffix.lower() in ARCHIVE_EXTENSIONS:
            self.open_archive(path)
            return
        self.leave_archive_mode()
        if path.is_dir():
            images = self.collect_images(path)
            index = 0
        elif path.is_file() and self.is_image(path):
            images = [path]
            index = 0
        else:
            QMessageBox.information(self, APP_NAME, self.tr_ui("画像ファイル、画像フォルダ、またはアーカイブを指定してください。"))
            return
        if not images:
            QMessageBox.information(self, APP_NAME, self.tr_ui("対応画像がありません。"))
            return
        self.set_image_list(images, index)
        self.config_data.last_dir = str(images[index].parent)
        self.push_recent_dir(images[index].parent)
        self.persist_config()
        # Keep navigation keys active after opening from a file dialog.
        self.viewer.setFocus(Qt.OtherFocusReason)
        if path.is_file() and self.is_image(path):
            self.folder_list_loading = True
            self.deferred_page_steps = 0
            self.collect_folder_images_async(path.parent, path)

    def open_path_deferred(self, path: Path) -> None:
        path = path.resolve()
        if path.is_file() and self.is_image(path):
            self.leave_archive_mode()
            self.set_image_list([path], 0, defer_work=True)
            self.viewer.setFocus(Qt.OtherFocusReason)
            self.folder_list_loading = True
            self.deferred_page_steps = 0
            self.config_data.last_dir = str(path.parent)
            self.push_recent_dir(path.parent)
            QTimer.singleShot(0, lambda p=path: self.collect_folder_images_async(p.parent, p))
            QTimer.singleShot(0, self.persist_config)
            return
        QTimer.singleShot(0, lambda p=path: self.open_path(p))

    def push_recent_dir(self, folder: Path) -> None:
        value = str(folder.resolve())
        items = [item for item in self.config_data.recent_dirs if item != value]
        items.insert(0, value)
        self.config_data.recent_dirs = items[:10]
        combo = getattr(self, "recent_dir_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self.config_data.recent_dirs)
            combo.blockSignals(False)

    def open_recent_folder(self) -> None:
        combo = getattr(self, "recent_dir_combo", None)
        if combo is None:
            return
        text = combo.currentText().strip()
        if not text:
            return
        path = Path(text)
        if path.exists() and path.is_dir():
            self.open_path(path)

    def set_image_list(self, images: list[Path], index: int, defer_work: bool = False) -> None:
        self.runtime_state.pdf_load_session_id += 1
        self.runtime_state.pdf_expected_pages = len(images)
        self.runtime_state.pdf_loaded_pages = len(images)
        self.runtime_state.pdf_loading = False
        self.image_paths = images
        self.refresh_image_path_sets()
        self.current_index = index
        self.navigation_history = [index] if images else []
        self.navigation_history_cursor = 0 if images else -1
        self.pending_page_steps = 0
        self.folder_list_loading = False
        self.deferred_page_steps = 0
        with self.original_cache_lock:
            self.original_cache.clear()
        self.failed_original_paths.clear()
        self.processed_cache.clear()
        self.viewer.pixmap_cache.clear()
        self.viewer.clear_pixmap_prefetch_state()
        self.prefetching_original_paths.clear()
        self.prefetching_processed_keys.clear()
        self.prefetch_viewer_plan = []
        self.prefetch_engine_plan = []
        self.prefetch_engine_done_paths.clear()
        self.prefetch_generation += 1
        self.update_prefetch_progress_bars()
        self.rebuild_thumbnail_items()
        if defer_work:
            self.display_current_image(defer_work=True)
        else:
            self.display_current_image()

    def queue_thumbnail_for_index(self, index: int) -> None:
        if not self.thumbnails_enabled() or not (0 <= index < len(self.image_paths)):
            return
        if index in self.thumbnail_ready_indexes or index in self.thumbnail_pending:
            return
        with self.thumbnail_lock:
            self.thumbnail_sequence += 1
            sequence = self.thumbnail_sequence
        priority = abs(index - max(0, self.current_index))
        self.thumbnail_pending.add(index)
        self.thumbnail_queue.put((priority, sequence, self.thumbnail_generation, index, str(self.image_paths[index])))

    def append_image_path_incremental(self, path: Path, display_name: str) -> None:
        resolved = self.normalized_path(path)
        if resolved in self.image_path_set:
            return
        self.image_paths.append(path)
        self.image_path_set.add(resolved)
        self.image_path_string_set.add(str(resolved))
        self.archive_display_names[resolved] = display_name

        index = len(self.image_paths) - 1
        if self.thumbnails_enabled() and hasattr(self, "thumbnail_list"):
            item = QListWidgetItem(str(index + 1))
            item.setData(Qt.UserRole, index)
            item.setToolTip(display_name)
            self.thumbnail_list.addItem(item)
            self.thumbnail_items.append(item)
            self.queue_thumbnail_for_index(index)

        self.update_page_position_slider()
        if self.current_index >= 0 and self.current_index < len(self.image_paths):
            current = self.image_paths[self.current_index]
            self.status_label.setText(
                f"{self.current_index + 1}/{len(self.image_paths)} {self.state_text('処理済み')}: {self.display_name(current)}"
            )

    def start_pdf_background_render(self, pdf_path: Path, temp_dir: Path, start_page: int, total_pages: int, session_id: int) -> None:
        def worker() -> None:
            try:
                if QPdfDocument is None:
                    raise ArchiveError("PDF support is unavailable.")
                document = QPdfDocument()
                document.load(str(pdf_path))
                if document.error() != QPdfDocument.Error.None_:
                    raise ArchiveError("PDF decoder error")
                for page_index in range(start_page, total_pages):
                    if self.runtime_state.pdf_load_session_id != session_id:
                        return
                    output_path = _render_pdf_page_image(
                        document,
                        pdf_path,
                        temp_dir,
                        page_index,
                        PDF_RENDER_SCALE,
                        PDF_MAX_RENDER_PIXELS,
                    )
                    display_name = f"{pdf_path.name} [page {page_index + 1}]"
                    self.signals.pdf_page_ready.emit(session_id, output_path, display_name, page_index + 1, total_pages)
                self.signals.pdf_load_done.emit(session_id, total_pages)
            except Exception as exc:
                self.signals.pdf_load_failed.emit(session_id, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def on_pdf_page_ready(self, session_id: int, page_path: Path, display_name: str, loaded_pages: int, total_pages: int) -> None:
        if session_id != self.runtime_state.pdf_load_session_id:
            return
        self.runtime_state.pdf_loaded_pages = max(self.runtime_state.pdf_loaded_pages, loaded_pages)
        self.runtime_state.pdf_expected_pages = max(self.runtime_state.pdf_expected_pages, total_pages)
        self.append_image_path_incremental(page_path, display_name)

    def on_pdf_load_done(self, session_id: int, total_pages: int) -> None:
        if session_id != self.runtime_state.pdf_load_session_id:
            return
        self.runtime_state.pdf_loading = False
        self.runtime_state.pdf_loaded_pages = max(self.runtime_state.pdf_loaded_pages, total_pages)
        self.runtime_state.pdf_expected_pages = max(self.runtime_state.pdf_expected_pages, total_pages)
        if self.archive_source_path is not None:
            self.append_log_if_visible(f"PDF expanded in background: {self.runtime_state.pdf_loaded_pages}/{self.runtime_state.pdf_expected_pages}")
        self.request_schedule_prefetch(0)

    def on_pdf_load_failed(self, session_id: int, reason: str) -> None:
        if session_id != self.runtime_state.pdf_load_session_id:
            return
        self.runtime_state.pdf_loading = False
        self.append_log_with_level(f"PDF background expansion failed: {reason}", LOG_LEVEL_WARN)

    def collect_folder_images_async(self, folder: Path, selected_path: Path) -> None:
        def worker() -> None:
            started = time.perf_counter()
            images = self.collect_images(folder)
            self.signals.profile_event.emit("フォルダ画像列挙", (time.perf_counter() - started) * 1000)
            self.signals.folder_images_ready.emit(images, selected_path.resolve())

        threading.Thread(target=worker, daemon=True).start()

    def on_folder_images_ready(self, images: list[Path], selected_path: Path) -> None:
        if not images:
            self.folder_list_loading = False
            return
        try:
            selected_index = images.index(selected_path)
        except ValueError:
            self.folder_list_loading = False
            return
        if not self.image_paths or self.normalized_path(self.image_paths[self.current_index]) != selected_path:
            self.folder_list_loading = False
            return
        self.image_paths = images
        self.refresh_image_path_sets()
        self.current_index = selected_index
        self.folder_list_loading = False
        state = "Displaying" if self.ui_language() == "en" else "表示中"
        self.status_label.setText(f"{self.current_index + 1}/{len(self.image_paths)} {state}: {self.display_name(selected_path)}")
        self.update_page_position_slider()
        self.update_window_title()
        self.rebuild_thumbnail_items()
        self.schedule_prefetch()
        self.viewer.setFocus(Qt.OtherFocusReason)
        if self.deferred_page_steps:
            steps = self.deferred_page_steps
            self.deferred_page_steps = 0
            QTimer.singleShot(0, lambda s=steps: self.queue_page_steps(s))

    def refresh_image_path_sets(self) -> None:
        self.image_path_set = set()
        for path in self.image_paths:
            self.image_path_set.add(self.normalized_path(path))
        self.image_path_string_set = {str(path) for path in self.image_path_set}

    def normalized_path(self, path: Path) -> Path:
        return path if path.is_absolute() else path.resolve()

    def normalized_path_text(self, path: Path) -> str:
        return str(self.normalized_path(path))

    def spread_mode_enabled(self) -> bool:
        check = getattr(self, "spread_mode_check", None)
        return bool(check.isChecked() if check is not None else self.config_data.spread_mode_enabled)

    def spread_anchor_index(self, index: int) -> int:
        if not self.spread_mode_enabled() or index <= 0:
            return index
        return index if index % 2 == 0 else index - 1

    def spread_pair_index(self, index: int) -> int | None:
        if not self.spread_mode_enabled():
            return None
        pair = index + 1
        return pair if 0 <= pair < len(self.image_paths) else None

    def compose_spread_image(self, left: QImage, right: QImage) -> QImage:
        return compose_side_by_side_images(left, right)

    def display_current_image(
        self,
        defer_work: bool = False,
        preserve_view: bool = False,
        navigation: bool = False,
        scroll_thumbnail: bool = True,
    ) -> None:
        if not self.image_paths or self.current_index < 0:
            return
        anchor = self.spread_anchor_index(self.current_index)
        if anchor != self.current_index:
            self.current_index = anchor
        profile_start = time.perf_counter()
        path = self.image_paths[self.current_index]
        source_start = time.perf_counter()
        source = self.load_original(path)
        self.record_profile("表示-元画像取得", (time.perf_counter() - source_start) * 1000)
        if source.isNull():
            next_index = self.find_next_loadable_image_index(self.current_index)
            if next_index is not None and next_index != self.current_index:
                self.current_index = next_index
                self.last_navigation_step = 1
                self.display_current_image(
                    defer_work=defer_work,
                    preserve_view=preserve_view,
                    navigation=navigation,
                    scroll_thumbnail=scroll_thumbnail,
                )
                return
            self.status_label.setText(
                "画像を読み込めませんでした。" if self.ui_language() != "en" else "Unable to load the image."
            )
            self.viewer.set_images(QImage(), None, preserve_view=False)
            self.update_page_position_slider()
            self.update_window_title(source=QImage(), processed=None, skipped=True)
            return
        cache_key = self.processing_key(path)
        processed_start = time.perf_counter()
        processed = self.processed_cache.get(cache_key)
        skipped = False
        if processed is None:
            existing = self.existing_processed_path(path)
            if existing is not None:
                processed = QImage(str(existing))
                if not processed.isNull():
                    self.processed_cache[cache_key] = processed
                    self._trim_processed_cache()
        if processed is None or processed.isNull():
            if self.should_skip_upscale(path):
                skipped = True
                state = "対象外"
            else:
                self.enqueue_upscale(path, front=True)
                state = f"{self.engine_label()}待ち"
            processed = None
        else:
            state = "処理済み"
        self.record_profile("表示-処理画像解決", (time.perf_counter() - processed_start) * 1000)

        display_source = source
        display_processed = processed
        pair_index = self.spread_pair_index(self.current_index)
        if pair_index is not None:
            pair_path = self.image_paths[pair_index]
            pair_source = self.load_original(pair_path)
            if not pair_source.isNull():
                pair_processed = self.processed_cache.get(self.processing_key(pair_path))
                if pair_processed is None:
                    existing_pair = self.existing_processed_path(pair_path)
                    if existing_pair is not None:
                        pair_processed = QImage(str(existing_pair))
                        if not pair_processed.isNull():
                            self.processed_cache[self.processing_key(pair_path)] = pair_processed
                            self._trim_processed_cache()
                if pair_processed is None or pair_processed.isNull():
                    if not self.should_skip_upscale(pair_path):
                        self.enqueue_upscale(pair_path, front=False)
                    pair_processed = None
                display_source = self.compose_spread_image(source, pair_source)
                if (processed is not None and not processed.isNull()) or (pair_processed is not None and not pair_processed.isNull()):
                    left_processed = processed if processed is not None and not processed.isNull() else source
                    right_processed = pair_processed if pair_processed is not None and not pair_processed.isNull() else pair_source
                    display_processed = self.compose_spread_image(left_processed, right_processed)
                else:
                    display_processed = None
        if navigation:
            self.viewer.begin_interactive_resample_delay()
        self.viewer.set_images(display_source, display_processed, preserve_view=preserve_view)
        self.viewer.pixmap_prefetch_done_keys.add(self.pixmap_progress_key("original", path))
        if processed is not None and not processed.isNull():
            self.viewer.pixmap_prefetch_done_keys.add(self.pixmap_progress_key("processed", path))
        self.status_label.setText(f"{self.current_index + 1}/{len(self.image_paths)} {self.state_text(state)}: {self.display_name(path)}")
        if pair_index is not None and pair_index < len(self.image_paths):
            pair_path = self.image_paths[pair_index]
            self.metadata_label.setText(
                f"{display_source.width()}x{display_source.height()} | spread | {path.name} + {pair_path.name}"
            )
        else:
            self.metadata_label.setText(
                f"{source.width()}x{source.height()} | {path.suffix.lower()} | {path.name}"
            )
        self.update_page_position_slider()
        self.update_window_title(source=display_source, processed=display_processed, skipped=skipped)
        if self.thumbnails_enabled():
            self.update_thumbnail_selection(scroll=scroll_thumbnail)
        self.record_navigation_history(self.current_index)
        self.request_borderless_fullscreen_enforce()
        self.request_schedule_prefetch(0 if defer_work else PREFETCH_DEBOUNCE_MS)
        self.record_profile("表示切替", (time.perf_counter() - profile_start) * 1000)

    def record_navigation_history(self, index: int) -> None:
        if self.navigation_history_blocked or index < 0:
            return
        if self.navigation_history and self.navigation_history_cursor >= 0 and self.navigation_history[self.navigation_history_cursor] == index:
            return
        if 0 <= self.navigation_history_cursor < len(self.navigation_history) - 1:
            self.navigation_history = self.navigation_history[: self.navigation_history_cursor + 1]
        self.navigation_history.append(index)
        if len(self.navigation_history) > 256:
            self.navigation_history = self.navigation_history[-256:]
        self.navigation_history_cursor = len(self.navigation_history) - 1

    def navigate_history(self, direction: int) -> None:
        if not self.image_paths or self.navigation_history_cursor < 0:
            return
        target = self.navigation_history_cursor + direction
        if target < 0 or target >= len(self.navigation_history):
            return
        index = self.navigation_history[target]
        if index < 0 or index >= len(self.image_paths):
            return
        self.navigation_history_cursor = target
        self.navigation_history_blocked = True
        try:
            self.current_index = index
            self.display_current_image(preserve_view=self.preserve_view_check.isChecked(), navigation=True)
        finally:
            self.navigation_history_blocked = False

    def update_window_title(self, source: QImage | None = None, processed: QImage | None = None, skipped: bool | None = None) -> None:
        if not self.image_paths:
            self.setWindowTitle(APP_NAME)
            return
        path = self.image_paths[self.current_index]
        if source is None:
            source = self.load_original(path)
        if processed is None:
            processed = self.processed_cache.get(self.processing_key(path))
        is_skipped = skipped if skipped is not None else self.should_skip_upscale(path)
        if processed and not processed.isNull():
            after = f"{processed.width()}x{processed.height()}"
        elif is_skipped:
            after = "Skipped" if self.ui_language() == "en" else "拡大処理対象外"
        else:
            after = "Processing" if self.ui_language() == "en" else "処理中"
        self.setWindowTitle(
            f"{self.display_name(path)} ({self.current_index + 1} / {len(self.image_paths)}) "
            f"[{source.width()}x{source.height()}] -> [{after}] - {APP_NAME}"
        )

    def load_original(self, path: Path) -> QImage:
        path = self.normalized_path(path)
        if path in self.failed_original_paths:
            return QImage()
        with self.original_cache_lock:
            cached = self.original_cache.get(path)
            if cached is not None:
                self.original_cache.move_to_end(path)
                return cached
        reader = QImageReader(str(path))
        reader.setAutoTransform(bool(self.config_data.exif_auto_orient))
        size = reader.size()
        if size.isValid():
            pixels = int(size.width()) * int(size.height())
            if pixels > self.config_data.max_safe_image_pixels:
                self.report_image_load_error(
                    path,
                    (
                        f"Image is too large ({size.width()}x{size.height()}, {pixels} px). "
                        f"Limit={self.config_data.max_safe_image_pixels} px"
                    ),
                )
                self.failed_original_paths.add(path)
                return QImage()
        started = time.perf_counter()
        image = reader.read()
        self.record_profile("元画像読込(UI)", (time.perf_counter() - started) * 1000)
        if image.isNull():
            self.report_image_load_error(path, reader.errorString().strip() or "Unknown decoder error")
            self.failed_original_paths.add(path)
            return QImage()
        with self.original_cache_lock:
            self.original_cache[path] = image
            while len(self.original_cache) > max(6, self.config_data.viewer_prefetch_count * 2 + 3):
                self.original_cache.popitem(last=False)
        return image

    def find_next_loadable_image_index(self, current_index: int) -> int | None:
        if not self.image_paths:
            return None
        total = len(self.image_paths)
        for offset in range(1, total):
            candidate = (current_index + offset) % total
            candidate_path = self.image_paths[candidate]
            if not self.load_original(candidate_path).isNull():
                return candidate
        return None

    def report_image_load_error(self, path: Path, detail: str) -> None:
        self.append_log_with_level(f"Image load failed: {self.display_name(path)} | {detail}", LOG_LEVEL_ERROR)

    def should_skip_upscale(self, path: Path) -> bool:
        return self.skip_tall_check.isChecked() and self.load_original(path).height() >= self.skip_height_spin.value()

    def queue_page_steps(self, steps: int) -> None:
        if not self.image_paths or steps == 0:
            return
        if abs(steps) >= 3:
            with self.work_queue.mutex:
                self.work_queue.queue.clear()
            self.queued_paths.clear()
            self.clear_prefetch_io_queue()
            self.prefetching_original_paths.clear()
            self.prefetching_processed_keys.clear()
        if self.folder_list_loading and len(self.image_paths) <= 1:
            self.deferred_page_steps = max(-999, min(999, self.deferred_page_steps + steps))
            return
        self.pending_page_steps = steps
        if not self.page_scroll_timer.isActive():
            self._drain_page_steps()

    def _drain_page_steps(self) -> None:
        if self.pending_page_steps == 0:
            self.page_scroll_timer.stop()
            return
        step = 1 if self.pending_page_steps > 0 else -1
        if self.show_relative_image(step):
            self.pending_page_steps -= step
            if self.pending_page_steps:
                self.page_scroll_timer.start(max(0, self.page_interval_spin.value()))
        else:
            self.pending_page_steps = 0

    def show_relative_image(self, step: int) -> bool:
        step_value = step * 2 if self.spread_mode_enabled() else step
        next_index = self.current_index + step_value
        if next_index < 0 or next_index >= len(self.image_paths):
            if not self.wrap_page_check.isChecked():
                return False
            next_index %= len(self.image_paths)
            next_index = self.spread_anchor_index(next_index)
        self.last_navigation_step = 1 if step > 0 else -1
        self.current_index = next_index
        self.display_current_image(preserve_view=self.preserve_view_check.isChecked(), navigation=True)
        return True

    def show_first_image(self) -> None:
        if self.image_paths:
            self.current_index = 0
            self.last_navigation_step = -1
            self.display_current_image(preserve_view=self.preserve_view_check.isChecked(), navigation=True)

    def show_last_image(self) -> None:
        if self.image_paths:
            last = len(self.image_paths) - 1
            self.current_index = self.spread_anchor_index(last)
            self.last_navigation_step = 1
            self.display_current_image(preserve_view=self.preserve_view_check.isChecked(), navigation=True)

    def matching_key_action(self, event: QEvent) -> str | None:
        key = event.key()
        modifiers = modifier_value(event.modifiers())
        signature = (key, modifiers)
        if signature in self.duplicate_keyboard_bindings:
            return None
        for action_id, bindings in self.config_data.key_bindings.items():
            binding = bindings.get("keyboard") if isinstance(bindings, dict) else None
            if not binding:
                continue
            if int(binding.get("key", 0)) == key and int(binding.get("modifiers", 0)) == modifiers:
                return action_id
        return None

    def perform_action(self, action_id: str) -> None:
        actions = {
            "open_image": self.open_image_dialog,
            "open_folder": self.open_folder_dialog,
            "next_page": lambda: self.queue_page_steps(1),
            "previous_page": lambda: self.queue_page_steps(-1),
            "last_page": self.show_last_image,
            "first_page": self.show_first_image,
            "toggle_fullscreen": self.toggle_fullscreen,
            "toggle_thumbnail_panel": self.toggle_thumbnail_panel,
            "toggle_side_panel": self.toggle_side_panel,
            "actual_size": self.viewer.zoom_to_actual_size,
            "fit_view": self.viewer.reset_display_state,
            "rotate_right": lambda: self.viewer.rotate_display(90),
            "rotate_left": lambda: self.viewer.rotate_display(-90),
            "flip_horizontal": lambda: self.viewer.flip_display(True),
            "flip_vertical": lambda: self.viewer.flip_display(False),
        }
        action = actions.get(action_id)
        if action is not None:
            action()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Space:
            self.queue_page_steps(1)
        elif event.key() == Qt.Key_Backspace:
            self.queue_page_steps(-1)
        else:
            action_id = self.matching_key_action(event)
            if action_id:
                self.perform_action(action_id)
            else:
                super().keyPressEvent(event)

    def toggle_compare_mode(self) -> None:
        if not ENABLE_COMPARE_MODE:
            return
        self.compare_check.setChecked(not self.compare_check.isChecked())
        self.on_compare_changed()

    def open_image_dialog(self) -> None:
        start = self.config_data.last_dir or str(Path.home())
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "画像を開く",
            start,
            "Images/Archives (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.pdf *.zip *.cbz *.rar *.cbr *.7z *.cb7);;All files (*.*)",
        )
        if path:
            self.open_path(Path(path))

    def open_folder_dialog(self) -> None:
        start = self.config_data.last_dir or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "フォルダを開く", start)
        if path:
            self.open_path(Path(path))

    def dragEnterEvent(self, event: QEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.viewer_host.setStyleSheet("border: 2px solid #2f80ff;")
            self.status_label.setText("ドロップして開く" if self.ui_language() != "en" else "Drop to open")

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.viewer_host.setStyleSheet("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QEvent) -> None:
        urls = event.mimeData().urls()
        self.viewer_host.setStyleSheet("")
        if urls:
            event.acceptProposedAction()
            self.activateWindow()
            self.raise_()
            self.open_path_deferred(Path(urls[0].toLocalFile()))

    def hide_side_panel(self) -> None:
        self.side_panel.hide()
        self.persist_config()
        self.layout_viewer_host()

    def show_side_panel(self) -> None:
        if self.config_data.side_panel_detached:
            self.detach_side_panel_for_overlay(visible=True)
            self.side_panel.show()
            self.side_panel.raise_()
            self.persist_config()
            self.layout_viewer_host()
            return
        if self.pin_button.isChecked():
            return
        if not self.side_panel.isVisible():
            self.overlay_hide_suppressed_until = time.monotonic() + SIDE_PANEL_HIDE_GRACE_SEC
            self.detach_side_panel_for_overlay(visible=True)
            self.side_panel.show()
            self.position_overlay_side_panel()
            self.side_panel.raise_()
            self.request_borderless_fullscreen_enforce()
            self.persist_config()
            self.layout_viewer_host()

    def toggle_side_panel(self) -> None:
        if self.config_data.side_panel_detached:
            self.side_panel.setVisible(not self.side_panel.isVisible())
            self.persist_config()
            self.layout_viewer_host()
            return
        self.pin_button.setChecked(not self.pin_button.isChecked())

    def toggle_thumbnail_panel(self) -> None:
        if not self.thumbnails_enabled():
            self.thumbnail_enabled_check.setChecked(True)
        self.thumbnail_pinned_check.setChecked(not self.thumbnail_pinned_check.isChecked())

    def is_cursor_over_side_panel(self) -> bool:
        if not self.side_panel.isVisible():
            return False
        local = self.side_panel.mapFromGlobal(QCursor.pos())
        return self.side_panel.rect().contains(local)

    def should_hide_overlay_panel(self) -> bool:
        if self.config_data.side_panel_detached:
            return False
        if self.overlay_resizing or self.overlay_modal_guard or self.pin_button.isChecked() or not self.side_panel_overlay:
            return False
        if QApplication.activePopupWidget() is not None:
            return False
        if time.monotonic() < self.overlay_hide_suppressed_until:
            return False
        local = self.side_panel.mapFromGlobal(QCursor.pos())
        rect = self.side_panel.rect()
        if self.current_side_panel_position() in {"left", "right"}:
            margin_rect = rect.adjusted(-SIDE_PANEL_HIDE_MARGIN, 0, SIDE_PANEL_HIDE_MARGIN, 0)
        else:
            margin_rect = rect.adjusted(0, -SIDE_PANEL_HIDE_MARGIN, 0, SIDE_PANEL_HIDE_MARGIN)
        if not margin_rect.contains(local):
            return True
        if not rect.contains(local):
            return False
        # Keep overlay visible while the cursor is inside the panel so controls remain operable.
        return False

    def _ensure_side_panel_width(self) -> None:
        self._apply_splitter_panel_width()

    def current_side_panel_position(self) -> str:
        position = str(getattr(self.config_data, "side_panel_position", "right"))
        return position if position in SIDE_PANEL_POSITIONS else "right"

    def splitter_side_panel_index(self) -> int:
        return 0 if self.current_side_panel_position() in {"left", "top"} else 1

    def splitter_is_horizontal(self) -> bool:
        return self.current_side_panel_position() in {"left", "right"}

    def splitter_primary_span(self) -> int:
        if self.splitter_is_horizontal():
            return self.splitter.width() or self.width()
        return self.splitter.height() or self.height()

    def apply_side_panel_position_in_splitter(self) -> None:
        if not hasattr(self, "splitter"):
            return
        self.splitter.setOrientation(Qt.Horizontal if self.splitter_is_horizontal() else Qt.Vertical)
        if self.splitter_side_panel_index() == 0:
            self.splitter.insertWidget(0, self.side_panel)
            self.splitter.insertWidget(1, self.viewer_host)
            self.splitter.setStretchFactor(0, 0)
            self.splitter.setStretchFactor(1, 1)
        else:
            self.splitter.insertWidget(0, self.viewer_host)
            self.splitter.insertWidget(1, self.side_panel)
            self.splitter.setStretchFactor(0, 1)
            self.splitter.setStretchFactor(1, 0)

    def current_side_panel_width(self) -> int:
        if self.side_panel_overlay:
            return int(self.side_panel_width)
        sizes = self.splitter.sizes()
        side_index = self.splitter_side_panel_index()
        if len(sizes) >= 2 and sizes[side_index] > 0:
            self.side_panel_width = self.clamped_side_panel_width(sizes[side_index])
            return self.side_panel_width
        return self.clamped_side_panel_width()

    def clamped_side_panel_width(self, width: int | None = None) -> int:
        total = max(1, self.splitter_primary_span() if hasattr(self, "splitter") else self.width())
        maximum = max(1, total // 2)
        base_minimum = self.side_panel.minimumWidth() if self.splitter_is_horizontal() else max(180, self.side_panel.minimumHeight())
        minimum = min(max(240 if self.splitter_is_horizontal() else 180, base_minimum), maximum)
        value = int(self.side_panel_width if width is None else width)
        return max(minimum, min(value, maximum))

    def _apply_splitter_panel_width(self) -> None:
        self.apply_side_panel_position_in_splitter()
        total = self.splitter_primary_span() or sum(self.splitter.sizes()) or self.width()
        if total <= 0:
            return
        panel_width = self.clamped_side_panel_width()
        side_index = self.splitter_side_panel_index()
        sizes = [max(1, total - panel_width), max(1, total - panel_width)]
        sizes[side_index] = panel_width
        sizes[1 - side_index] = max(1, total - panel_width)
        self.adjusting_splitter = True
        self.splitter.setSizes(sizes)
        self.adjusting_splitter = False

    def attach_side_panel_to_splitter(self, visible: bool = True) -> None:
        if self.side_panel_overlay:
            self.side_panel.hide()
            self.side_panel.setParent(self.splitter, Qt.Widget)
            self.side_panel.installEventFilter(self)
            self.side_panel_overlay = False
        self.apply_side_panel_position_in_splitter()
        self.side_panel.setVisible(visible)
        if visible:
            self._apply_splitter_panel_width()
            QTimer.singleShot(0, self._apply_splitter_panel_width)

    def detach_side_panel_for_overlay(self, visible: bool = False) -> None:
        if self.config_data.side_panel_detached:
            needs_top_level = (self.side_panel.parent() is not None) or (not self.side_panel.isWindow())
            if needs_top_level:
                if not getattr(self, "initializing", False):
                    self.side_panel_width = self.current_side_panel_width()
                self.config_data.side_panel_width = self.side_panel_width
                self.side_panel.hide()
                self.side_panel.setParent(
                    None,
                    Qt.Window
                    | Qt.WindowTitleHint
                    | Qt.WindowSystemMenuHint
                    | Qt.WindowMinimizeButtonHint
                    | Qt.WindowCloseButtonHint,
                )
                self.side_panel.setWindowTitle(f"{APP_NAME} - 設定")
                self.side_panel.installEventFilter(self)
                self.side_panel_overlay = True
            rect = getattr(self.config_data, "side_panel_window_rect", None)
            restored = self._restore_side_panel_window_rect(rect)
            if restored is not None:
                x, y, w, h = restored
                self.side_panel.setGeometry(x, y, w, h)
            self.side_panel.setVisible(visible)
            if visible:
                self.side_panel.raise_()
            return
        needs_overlay_reparent = self.side_panel.isWindow() or self.side_panel.parent() is None
        if not self.side_panel_overlay or needs_overlay_reparent:
            if not getattr(self, "initializing", False):
                self.side_panel_width = self.current_side_panel_width()
            self.config_data.side_panel_width = self.side_panel_width
            self.side_panel.hide()
            self.side_panel.setParent(self, Qt.Widget)
            self.side_panel.installEventFilter(self)
            self.side_panel_overlay = True
            if not needs_overlay_reparent:
                self.adjusting_splitter = True
                self.splitter.setSizes([max(1, self.splitter.width()), 0])
                self.adjusting_splitter = False
        self.position_overlay_side_panel()
        self.side_panel.setVisible(visible)

    def position_overlay_side_panel(self) -> None:
        if self.config_data.side_panel_detached:
            return
        if not self.side_panel_overlay:
            return
        central = self.centralWidget().geometry()
        position = self.current_side_panel_position()
        extent = min(
            self.clamped_side_panel_width(),
            max(1, (central.width() // 2) if position in {"left", "right"} else (central.height() // 2)),
        )
        if position == "left":
            self.side_panel.setGeometry(central.left(), central.top(), extent, central.height())
        elif position == "right":
            self.side_panel.setGeometry(central.right() - extent + 1, central.top(), extent, central.height())
        elif position == "top":
            self.side_panel.setGeometry(central.left(), central.top(), central.width(), extent)
        else:
            self.side_panel.setGeometry(central.left(), central.bottom() - extent + 1, central.width(), extent)

    def on_splitter_moved(self, _pos: int, _index: int) -> None:
        if self.adjusting_splitter or self.side_panel_overlay:
            return
        sizes = self.splitter.sizes()
        if len(sizes) < 2:
            return
        total = sum(sizes)
        side_index = self.splitter_side_panel_index()
        minimum_size = self.side_panel.minimumWidth() if self.splitter_is_horizontal() else max(180, self.side_panel.minimumHeight())
        max_panel = max(minimum_size, total // 2)
        panel = min(sizes[side_index], max_panel)
        panel = max(minimum_size, panel)
        if panel != sizes[side_index]:
            self.adjusting_splitter = True
            resized = [max(1, total - panel), max(1, total - panel)]
            resized[side_index] = panel
            resized[1 - side_index] = max(1, total - panel)
            self.splitter.setSizes(resized)
            self.adjusting_splitter = False
        self.side_panel_width = panel
        self.config_data.side_panel_width = panel
        if hasattr(self, "side_panel_width_spin") and self.side_panel_width_spin.value() != panel:
            self.side_panel_width_spin.blockSignals(True)
            self.side_panel_width_spin.setValue(panel)
            self.side_panel_width_spin.blockSignals(False)
        self.persist_config()

    def on_side_panel_width_changed(self, value: int) -> None:
        if not hasattr(self, "side_panel"):
            return
        panel = self.clamped_side_panel_width(value)
        self.side_panel_width = panel
        self.config_data.side_panel_width = panel
        if self.side_panel_overlay:
            self.position_overlay_side_panel()
        else:
            self._apply_splitter_panel_width()
        if self.side_panel_width_spin.value() != panel:
            self.side_panel_width_spin.blockSignals(True)
            self.side_panel_width_spin.setValue(panel)
            self.side_panel_width_spin.blockSignals(False)
        self.persist_config()

    def on_side_panel_position_changed(self) -> None:
        if not hasattr(self, "side_panel_position_combo"):
            return
        position = self.side_panel_position_combo.currentData() or "right"
        if position not in SIDE_PANEL_POSITIONS:
            position = "right"
        self.config_data.side_panel_position = position
        if not self.config_data.side_panel_detached and self.pin_button.isChecked():
            self.attach_side_panel_to_splitter(visible=True)
        elif not self.config_data.side_panel_detached and self.side_panel_overlay:
            self.position_overlay_side_panel()
        self.persist_config()

    def on_side_panel_detached_changed(self) -> None:
        detached = bool(self.side_panel_detach_check.isChecked()) if hasattr(self, "side_panel_detach_check") else False
        self.config_data.side_panel_detached = detached
        if hasattr(self, "pin_button"):
            self.pin_button.setEnabled(not detached)
        if detached:
            self.detach_side_panel_for_overlay(visible=True)
        else:
            if self.pin_button.isChecked():
                self.attach_side_panel_to_splitter(visible=True)
            else:
                self.detach_side_panel_for_overlay(visible=False)
        self.persist_config()

    def toggle_fullscreen(self) -> None:
        detached = bool(self.config_data.side_panel_detached)
        if self.is_app_fullscreen():
            self._show_fullscreen_cursor()
            self.borderless_fullscreen = False
            self.fullscreen_enforce_pending = False
            self.setWindowState(Qt.WindowNoState)
            self.setWindowFlags(self.before_fullscreen_flags)
            if self.before_fullscreen_geometry.isValid():
                self.setGeometry(self.before_fullscreen_geometry)
            self.setStyleSheet("")
            self.show()
            restore_state = self.before_fullscreen_state & ~Qt.WindowFullScreen
            if restore_state != Qt.WindowNoState:
                self.setWindowState(restore_state)
            if detached:
                self.detach_side_panel_for_overlay(visible=self.config_data.side_panel_visible)
            elif self.pin_button.isChecked():
                self.attach_side_panel_to_splitter(visible=True)
            else:
                self.detach_side_panel_for_overlay(visible=False)
        else:
            self.before_fullscreen_geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
            self.before_fullscreen_flags = self.windowFlags()
            self.before_fullscreen_state = self.windowState() & ~Qt.WindowFullScreen
            pinned = self.pin_button.isChecked()
            self.side_panel_visible_before_fullscreen = self.side_panel.isVisible() or pinned
            if detached:
                self.detach_side_panel_for_overlay(visible=self.config_data.side_panel_visible)
            elif pinned:
                self.attach_side_panel_to_splitter(visible=True)
            else:
                self.detach_side_panel_for_overlay(visible=False)
                self.side_panel.hide()
                self.side_panel.setParent(None)
            self.borderless_fullscreen = True
            self.setWindowState(Qt.WindowNoState)
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
            self.setStyleSheet("QMainWindow { background: #000000; }")
            target = self.borderless_fullscreen_geometry()
            if target.isValid():
                self.setGeometry(target)
            self.show()
            if detached:
                self.detach_side_panel_for_overlay(visible=self.config_data.side_panel_visible)
            elif pinned:
                self.attach_side_panel_to_splitter(visible=True)
            else:
                self.side_panel.setParent(self)
                self.side_panel.installEventFilter(self)
                self.side_panel_overlay = True
                self.position_overlay_side_panel()
            self.raise_()
            self.request_borderless_fullscreen_enforce()
            self._apply_fullscreen_cursor()

    def borderless_fullscreen_geometry(self) -> QRect:
        screen = self.screen() or QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return QRect()
        geometry = QRect(screen.geometry())
        if os.name == "nt":
            overscan = BORDERLESS_FULLSCREEN_OVERSCAN
            geometry.adjust(-overscan, -overscan, overscan, overscan)
        return geometry

    def request_borderless_fullscreen_enforce(self) -> None:
        if not self.is_app_fullscreen() or self.fullscreen_enforce_pending:
            return
        self.fullscreen_enforce_pending = True
        QTimer.singleShot(0, self.enforce_borderless_fullscreen)

    def enforce_borderless_fullscreen(self) -> None:
        self.fullscreen_enforce_pending = False
        if not self.is_app_fullscreen():
            return
        changed_flags = False
        state = self.windowState()
        if state & Qt.WindowFullScreen:
            self.setWindowState(state & ~Qt.WindowFullScreen)
        desired_flags = Qt.Window | Qt.FramelessWindowHint
        if self.windowFlags() != desired_flags:
            self.setWindowFlags(desired_flags)
            changed_flags = True
        target = self.borderless_fullscreen_geometry()
        if target.isValid() and self.geometry() != target:
            self.setGeometry(target)
        if changed_flags or not self.isVisible():
            self.show()
        if self.side_panel_overlay:
            self.position_overlay_side_panel()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is getattr(self, "viewer_host", None):
            if event.type() == QEvent.Resize:
                self.layout_viewer_host()
        if watched is getattr(self, "side_panel_header", None) and self.config_data.side_panel_detached:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self.detached_panel_dragging = True
                self.detached_panel_drag_offset = event.globalPosition().toPoint() - self.side_panel.frameGeometry().topLeft()
                return True
            if event.type() == QEvent.MouseMove and self.detached_panel_dragging and (event.buttons() & Qt.LeftButton):
                new_pos = event.globalPosition().toPoint() - self.detached_panel_drag_offset
                self.side_panel.move(new_pos)
                return True
            if event.type() == QEvent.MouseButtonRelease and self.detached_panel_dragging:
                self.detached_panel_dragging = False
                self.persist_config()
                return True
        if watched is getattr(self, "thumbnail_panel", None) or watched is getattr(self, "thumbnail_list", None) or watched is getattr(getattr(self, "thumbnail_list", None), "viewport", lambda: None)():
            if event.type() in {QEvent.MouseButtonPress, QEvent.MouseMove, QEvent.MouseButtonRelease}:
                global_pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else QCursor.pos()
                panel_pos = self.thumbnail_panel.mapFromGlobal(global_pos)
                if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and panel_pos.y() <= THUMBNAIL_RESIZE_GRIP:
                    self.thumbnail_resizing = True
                    self.thumbnail_panel.setCursor(Qt.SizeVerCursor)
                    return True
                if event.type() == QEvent.MouseMove:
                    if self.thumbnail_resizing:
                        host_pos = self.viewer_host.mapFromGlobal(global_pos)
                        self.thumbnail_height = self.clamped_thumbnail_height(self.viewer_host.height() - host_pos.y())
                        self.config_data.thumbnail_height = self.thumbnail_height
                        self.config_data.thumbnail_size = self.thumbnail_icon_size()
                        self.thumbnail_hide_suppressed_until = time.monotonic() + THUMBNAIL_HIDE_GRACE_SEC
                        self.layout_viewer_host()
                        return True
                    self.thumbnail_panel.setCursor(Qt.SizeVerCursor if panel_pos.y() <= THUMBNAIL_RESIZE_GRIP else Qt.ArrowCursor)
                if event.type() == QEvent.MouseButtonRelease and self.thumbnail_resizing:
                    self.thumbnail_resizing = False
                    self.thumbnail_panel.unsetCursor()
                    self.thumbnail_hide_suppressed_until = time.monotonic() + THUMBNAIL_HIDE_GRACE_SEC
                    self.thumbnail_resize_refresh_timer.start(1)
                    self.persist_config()
                    return True
            if event.type() in {QEvent.Leave, QEvent.Hide} and not self.thumbnails_pinned():
                QTimer.singleShot(THUMBNAIL_HIDE_DELAY_MS, self.hide_thumbnail_overlay)
            elif event.type() == QEvent.MouseMove and not self.thumbnails_pinned():
                self.show_thumbnail_overlay()
        if watched is getattr(self, "side_panel", None):
            if self.config_data.side_panel_detached:
                if event.type() == QEvent.Close:
                    self.config_data.side_panel_visible = False
                    self.persist_config()
                    self.layout_viewer_host()
                elif event.type() == QEvent.Hide and not self.closing:
                    self.config_data.side_panel_visible = False
                    self.persist_config()
                    self.layout_viewer_host()
                elif event.type() == QEvent.Show and not self.closing:
                    self.config_data.side_panel_visible = True
                    self.persist_config()
                    self.layout_viewer_host()
            if self.side_panel_overlay and not self.pin_button.isChecked() and not self.config_data.side_panel_detached:
                position = self.current_side_panel_position()
                if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                    if position == "right":
                        hit_grip = event.position().x() <= 18
                        cursor_shape = Qt.SizeHorCursor
                    elif position == "left":
                        hit_grip = event.position().x() >= max(0, self.side_panel.width() - 18)
                        cursor_shape = Qt.SizeHorCursor
                    elif position == "top":
                        hit_grip = event.position().y() >= max(0, self.side_panel.height() - 18)
                        cursor_shape = Qt.SizeVerCursor
                    else:
                        hit_grip = event.position().y() <= 18
                        cursor_shape = Qt.SizeVerCursor
                    if hit_grip:
                        self.overlay_resizing = True
                        self.side_panel.setCursor(cursor_shape)
                        return True
                if event.type() == QEvent.MouseMove:
                    if self.overlay_resizing:
                        local = self.mapFromGlobal(event.globalPosition().toPoint())
                        panel_geometry = self.side_panel.geometry()
                        if position == "right":
                            extent = panel_geometry.right() - local.x() + 1
                        elif position == "left":
                            extent = local.x() - panel_geometry.left() + 1
                        elif position == "top":
                            extent = local.y() - panel_geometry.top() + 1
                        else:
                            extent = panel_geometry.bottom() - local.y() + 1
                        self.side_panel_width = self.clamped_side_panel_width(extent)
                        self.config_data.side_panel_width = self.side_panel_width
                        self.position_overlay_side_panel()
                        return True
                    if position == "right":
                        hover_grip = event.position().x() <= 18
                        cursor_shape = Qt.SizeHorCursor
                    elif position == "left":
                        hover_grip = event.position().x() >= max(0, self.side_panel.width() - 18)
                        cursor_shape = Qt.SizeHorCursor
                    elif position == "top":
                        hover_grip = event.position().y() >= max(0, self.side_panel.height() - 18)
                        cursor_shape = Qt.SizeVerCursor
                    else:
                        hover_grip = event.position().y() <= 18
                        cursor_shape = Qt.SizeVerCursor
                    self.side_panel.setCursor(cursor_shape if hover_grip else Qt.ArrowCursor)
                if event.type() == QEvent.MouseButtonRelease and self.overlay_resizing:
                    self.overlay_resizing = False
                    self.side_panel.unsetCursor()
                    self.persist_config()
                    return True
                if event.type() == QEvent.Leave:
                    if self.should_hide_overlay_panel():
                        QTimer.singleShot(SIDE_PANEL_HIDE_DELAY_MS, self.hide_overlay_side_panel_if_needed)
                if event.type() == QEvent.Hide:
                    QTimer.singleShot(SIDE_PANEL_HIDE_DELAY_MS, self.hide_overlay_side_panel_if_needed)
        elif watched is self.viewer and event.type() == QEvent.MouseMove:
            if self.is_app_fullscreen():
                self.schedule_fullscreen_ui_auto_hide()
            if self.thumbnails_enabled() and not self.thumbnails_pinned():
                trigger_margin = min(self.viewer.height(), self.thumbnail_panel_height())
                if event.position().y() >= self.viewer.height() - trigger_margin:
                    self.show_thumbnail_overlay()
                elif self.thumbnail_overlay_visible and not self.is_cursor_over_thumbnail_panel():
                    self.hide_thumbnail_overlay()
            if not self.pin_button.isChecked() and not self.config_data.side_panel_detached:
                position = self.current_side_panel_position()
                trigger_extent = min(
                    self.clamped_side_panel_width(),
                    max(1, (self.viewer.width() // 2) if position in {"left", "right"} else (self.viewer.height() // 2)),
                )
                x = event.position().x()
                y = event.position().y()
                if (
                    (position == "right" and x >= self.viewer.width() - trigger_extent)
                    or (position == "left" and x <= trigger_extent)
                    or (position == "top" and y <= trigger_extent)
                    or (position == "bottom" and y >= self.viewer.height() - trigger_extent)
                ):
                    self.show_side_panel()
                elif self.side_panel_overlay and self.side_panel.isVisible() and self.should_hide_overlay_panel():
                    self.side_panel.hide()
                    self.persist_config()
            if self.is_app_fullscreen() and self.fullscreen_cursor_hidden:
                self._show_fullscreen_cursor()
                self.schedule_fullscreen_ui_auto_hide()
        return super().eventFilter(watched, event)

    def schedule_fullscreen_ui_auto_hide(self, delay_ms: int = 1200) -> None:
        if not self.is_app_fullscreen():
            return
        self.fullscreen_ui_hide_timer.start(max(100, int(delay_ms)))

    def hide_fullscreen_ui_if_idle(self) -> None:
        if not self.is_app_fullscreen():
            return
        if self.thumbnails_enabled() and not self.thumbnails_pinned() and self.thumbnail_overlay_visible and not self.is_cursor_over_thumbnail_panel():
            self.hide_thumbnail_overlay()
        if self.side_panel_overlay and self.side_panel.isVisible() and self.should_hide_overlay_panel():
            self.side_panel.hide()
            self.persist_config()
        if self.hide_cursor_fullscreen_check.isChecked():
            self._apply_fullscreen_cursor()

    def hide_overlay_side_panel_if_needed(self) -> None:
        if self.should_hide_overlay_panel():
            self.side_panel.hide()
            self.persist_config()

    def on_side_panel_pin_changed(self, pinned: bool) -> None:
        if self.config_data.side_panel_detached:
            return
        self.pin_button.setText(self.tr_ui("固定中" if pinned else "自動表示"))
        if pinned:
            self.attach_side_panel_to_splitter(visible=True)
        else:
            keep_visible = self.is_cursor_over_side_panel()
            self.overlay_hide_suppressed_until = time.monotonic() + SIDE_PANEL_HIDE_GRACE_SEC
            self.detach_side_panel_for_overlay(visible=keep_visible)
            if self.side_panel.isVisible():
                self.side_panel.raise_()
        self.persist_config()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.layout_viewer_host()
        if self.side_panel_overlay:
            self.position_overlay_side_panel()
        elif hasattr(self, "splitter"):
            self._apply_splitter_panel_width()
        self.request_borderless_fullscreen_enforce()

    def _apply_fullscreen_cursor(self) -> None:
        if self.is_app_fullscreen() and self.hide_cursor_fullscreen_check.isChecked() and not self.fullscreen_cursor_hidden:
            QApplication.setOverrideCursor(QCursor(Qt.BlankCursor))
            self.fullscreen_cursor_hidden = True

    def _show_fullscreen_cursor(self) -> None:
        if self.fullscreen_cursor_hidden:
            QApplication.restoreOverrideCursor()
            self.fullscreen_cursor_hidden = False

    def is_app_fullscreen(self) -> bool:
        return self.borderless_fullscreen

    def update_zoom_label(self, scale: float) -> None:
        precision = int(getattr(self.config_data, "zoom_label_precision", 0))
        percent_value = max(0.01, scale * 100)
        prefix = "Zoom" if self.ui_language() == "en" else "ズーム"
        self.zoom_label.setText(f"{prefix}: {percent_value:.{precision}f}%")
        if hasattr(self, "zoom_slider") and not self.zoom_slider.isSliderDown():
            self.zoom_slider.blockSignals(True)
            slider_value = int(round(percent_value))
            self.zoom_slider.setValue(max(self.zoom_slider.minimum(), min(self.zoom_slider.maximum(), slider_value)))
            self.zoom_slider.blockSignals(False)

    def on_zoom_slider_changed(self, value: int) -> None:
        self.viewer.set_actual_zoom_percent(value)

    def on_viewer_split_changed(self, value: int) -> None:
        slider = getattr(self, "compare_slider", None)
        if slider is None:
            return
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)
        self.config_data.compare_split = value

    def reset_compare_split(self) -> None:
        slider = getattr(self, "compare_slider", None)
        if slider is None:
            return
        slider.setValue(500)
        self.on_compare_changed()

    def on_compare_changed(self) -> None:
        if not ENABLE_COMPARE_MODE:
            self.config_data.compare_enabled = False
            self.config_data.compare_diff_highlight = False
            self.viewer.set_compare(False, 500, "#ffffff", 2, False, False, False, 24)
            return
        line_edit = getattr(self, "compare_line_edit", None)
        compare_check = getattr(self, "compare_check", None)
        compare_slider = getattr(self, "compare_slider", None)
        compare_line_width_spin = getattr(self, "compare_line_width_spin", None)
        compare_swap_check = getattr(self, "compare_swap_check", None)
        compare_shift_check = getattr(self, "compare_shift_check", None)
        if (
            line_edit is None
            or compare_check is None
            or compare_slider is None
            or compare_line_width_spin is None
            or compare_swap_check is None
            or compare_shift_check is None
        ):
            return
        line_color = line_edit.text().strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", line_color):
            return
        diff_check = getattr(self, "compare_diff_highlight_check", None)
        diff_spin = getattr(self, "compare_diff_threshold_spin", None)
        self.viewer.set_compare(
            compare_check.isChecked(),
            compare_slider.value(),
            line_color,
            compare_line_width_spin.value(),
            compare_swap_check.isChecked(),
            compare_shift_check.isChecked(),
            bool(diff_check.isChecked()) if diff_check is not None else False,
            int(diff_spin.value()) if diff_spin is not None else 24,
        )
        self.persist_config()

    def on_background_changed(self) -> None:
        color = self.background_edit.text().strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            return
        self.viewer.set_background(color)
        self.persist_config()

    def on_resample_settings_changed(self) -> None:
        self.cpu_resample_combo.setEnabled(self.cpu_resample_check.isChecked())
        self.viewer.set_resample_options(self.cpu_resample_check.isChecked(), self.current_resample_algorithm())
        self.persist_config()

    def choose_background_color(self) -> None:
        color = self.choose_simple_color(self.background_edit.text(), "Select background color" if self.ui_language() == "en" else "背景色を選択")
        if color:
            self.background_edit.setText(color)
            self.on_background_changed()

    def choose_compare_line_color(self) -> None:
        compare_line_edit = getattr(self, "compare_line_edit", None)
        if compare_line_edit is None:
            return
        color = self.choose_simple_color(compare_line_edit.text(), "Select compare divider color" if self.ui_language() == "en" else "比較境界線の色を選択")
        if color:
            compare_line_edit.setText(color)
            self.on_compare_changed()

    def choose_simple_color(self, current: str, title: str) -> str | None:
        self.overlay_modal_guard = True
        self.overlay_hide_suppressed_until = time.monotonic() + 3600
        if self.side_panel_overlay and not self.pin_button.isChecked() and not self.side_panel.isVisible():
            self.show_side_panel()
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        red = QSpinBox()
        green = QSpinBox()
        blue = QSpinBox()
        for spin in (red, green, blue):
            spin.setRange(0, 255)
        color = QColor(current if re.fullmatch(r"#[0-9a-fA-F]{6}", current or "") else DEFAULT_BACKGROUND_COLOR)
        red.setValue(color.red())
        green.setValue(color.green())
        blue.setValue(color.blue())
        preview = QLabel()
        preview.setFixedHeight(40)
        hex_edit = QLineEdit(color.name().upper())

        def update_from_rgb() -> None:
            value = QColor(red.value(), green.value(), blue.value()).name().upper()
            hex_edit.blockSignals(True)
            hex_edit.setText(value)
            hex_edit.blockSignals(False)
            preview.setStyleSheet(f"background: {value}; border: 1px solid palette(mid);")

        def update_from_hex() -> None:
            value = hex_edit.text().strip()
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                return
            qcolor = QColor(value)
            for spin, component in ((red, qcolor.red()), (green, qcolor.green()), (blue, qcolor.blue())):
                spin.blockSignals(True)
                spin.setValue(component)
                spin.blockSignals(False)
            preview.setStyleSheet(f"background: {qcolor.name().upper()}; border: 1px solid palette(mid);")

        rgb_labels = (("Red", red), ("Green", green), ("Blue", blue)) if self.ui_language() == "en" else (("赤", red), ("緑", green), ("青", blue))
        for label, spin in rgb_labels:
            spin.valueChanged.connect(update_from_rgb)
            form.addRow(label, spin)
        hex_edit.editingFinished.connect(update_from_hex)
        form.addRow("HEX", hex_edit)
        layout.addWidget(preview)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(DIALOG_ACCEPT_TEXT)
        buttons.button(QDialogButtonBox.Cancel).setText(self.tr_ui("キャンセル"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        update_from_rgb()
        try:
            if dialog.exec() == QDialog.Accepted:
                value = hex_edit.text().strip().upper()
                return value if re.fullmatch(r"#[0-9A-F]{6}", value) else None
            return None
        finally:
            self.overlay_modal_guard = False
            self.overlay_hide_suppressed_until = time.monotonic() + SIDE_PANEL_HIDE_GRACE_SEC

    def on_general_settings_changed(self) -> None:
        self.viewer.set_horizontal_wheel_options(
            self.horizontal_wheel_check.isChecked(),
            self.horizontal_wheel_invert_check.isChecked(),
        )
        self.ensure_thumbnail_worker_count()
        self.auto_tune_pixmap_cache_limit()
        self.update_zoom_label(self.viewer.current_scale())
        self.persist_config()
        if self.is_app_fullscreen():
            if self.hide_cursor_fullscreen_check.isChecked():
                self._apply_fullscreen_cursor()
            else:
                self._show_fullscreen_cursor()

    def on_spread_mode_changed(self) -> None:
        self.persist_config()
        if self.image_paths:
            self.display_current_image(preserve_view=self.preserve_view_check.isChecked())

    def auto_tune_pixmap_cache_limit(self) -> None:
        prefetch = max(1, self.viewer_prefetch_spin.value())
        workers = self.thumbnail_worker_spin.value() if hasattr(self, "thumbnail_worker_spin") else int(self.config_data.thumbnail_worker_count)
        limit = prefetch * 2 + 8 + max(0, workers - 1) * 4
        self.viewer.set_pixmap_cache_limit(limit)

    def on_settings_search_changed(self, text: str) -> None:
        keyword = text.strip().lower()
        widget_names = [
            "cleanup_check",
            "language_combo",
            "viewer_prefetch_spin",
            "thumbnail_worker_spin",
            "sort_mode_combo",
            "side_panel_width_spin",
            "cpu_resample_check",
            "cpu_resample_combo",
            "background_edit",
            "compare_check",
            "compare_slider",
            "compare_line_edit",
            "compare_line_width_spin",
            "compare_swap_check",
            "compare_shift_check",
            "page_interval_spin",
            "zoom_precision_spin",
            "page_jump_spin",
            "invert_page_position_check",
            "thumbnail_enabled_check",
            "thumbnail_pinned_check",
            "wrap_page_check",
            "preserve_view_check",
            "spread_mode_check",
            "exif_auto_orient_check",
            "slideshow_enabled_check",
            "slideshow_interval_spin",
            "slideshow_pause_processing_check",
            "horizontal_wheel_check",
            "horizontal_wheel_invert_check",
        ]
        widgets: list[QWidget] = [getattr(self, name) for name in widget_names if hasattr(self, name)]
        for widget in widgets:
            searchable = " ".join(filter(None, [widget.toolTip(), widget.whatsThis(), widget.accessibleName(), widget.objectName()])).lower()
            if not searchable and isinstance(widget, QCheckBox):
                searchable = widget.text().lower()
            matched = not keyword or keyword in searchable
            widget.setVisible(matched)
        self.layout_viewer_host()

    def on_slideshow_settings_changed(self) -> None:
        enabled = self.slideshow_enabled_check.isChecked()
        interval_ms = max(1, self.slideshow_interval_spin.value()) * 1000
        self.slideshow_interval_spin.setEnabled(enabled)
        self.slideshow_pause_processing_check.setEnabled(enabled)
        if enabled:
            self.slideshow_timer.start(interval_ms)
        else:
            self.slideshow_timer.stop()
        self.persist_config()

    def on_slideshow_tick(self) -> None:
        if not self.image_paths or not self.slideshow_enabled_check.isChecked():
            return
        if self.slideshow_pause_processing_check.isChecked():
            current = self.image_paths[self.current_index] if 0 <= self.current_index < len(self.image_paths) else None
            if current is not None:
                normalized = self.normalized_path(current)
                if normalized in self.processing_paths or normalized in self.queued_paths:
                    return
        self.queue_page_steps(1)

    def on_exif_orientation_changed(self) -> None:
        with self.original_cache_lock:
            self.original_cache.clear()
        self.failed_original_paths.clear()
        self.persist_config()
        if self.image_paths:
            self.display_current_image(preserve_view=self.preserve_view_check.isChecked())

    def _toggle_path_tag(self, entries: list[str], path: Path) -> bool:
        key = self.normalized_path_text(path)
        if key in entries:
            entries.remove(key)
            return False
        entries.append(key)
        return True

    def toggle_current_bookmark(self) -> None:
        if not self.image_paths or self.current_index < 0:
            return
        state = self._toggle_path_tag(self.config_data.bookmarks, self.image_paths[self.current_index])
        self.status_label.setText("ブックマーク追加" if state else "ブックマーク解除")
        self.persist_config()

    def toggle_current_favorite(self) -> None:
        if not self.image_paths or self.current_index < 0:
            return
        state = self._toggle_path_tag(self.config_data.favorites, self.image_paths[self.current_index])
        self.status_label.setText("お気に入り追加" if state else "お気に入り解除")
        self.persist_config()

    def _jump_to_tagged_index(self, entries: list[str]) -> None:
        if not self.image_paths:
            return
        tagged = set(entries)
        if not tagged:
            return
        for step in range(1, len(self.image_paths) + 1):
            index = (self.current_index + step) % len(self.image_paths)
            if self.normalized_path_text(self.image_paths[index]) in tagged:
                self.last_navigation_step = 1
                self.current_index = index
                self.display_current_image(preserve_view=self.preserve_view_check.isChecked(), navigation=True)
                return

    def jump_to_next_bookmark(self) -> None:
        self._jump_to_tagged_index(self.config_data.bookmarks)

    def jump_to_next_favorite(self) -> None:
        self._jump_to_tagged_index(self.config_data.favorites)

    def on_language_changed(self) -> None:
        self.config_data.ui_language = self.language_combo.currentData() or "ja"
        self.apply_language()
        self.persist_config()

    def on_settings_tab_changed(self, index: int) -> None:
        self.config_data.settings_tab = SETTINGS_TABS[max(0, min(len(SETTINGS_TABS) - 1, index))]
        self.persist_config()

    def on_engine_changed(self, *_args) -> None:
        previous_engine = self.config_data.engine
        previous_text = self.command_edit.text().strip()
        if previous_engine == ENGINE_REALESRGAN:
            self.config_data.realesrgan_command_template = previous_text or DEFAULT_REALESRGAN_TEMPLATE
        else:
            self.config_data.realcugan_command_template = previous_text or DEFAULT_REALCUGAN_TEMPLATE
        self.config_data.engine = self.current_engine()
        self.apply_engine_ui()
        self.refresh_engine_version_info()
        self.on_processing_settings_changed()

    def on_cleanup_changed(self) -> None:
        self.persist_config()
        if self.cleanup_check.isChecked():
            QMessageBox.information(
                self,
                APP_NAME,
                f"次回起動時に、{APP_SHORT_NAME} が作成した古い一時フォルダと一時PNGを削除します。\n\n"
                "このチェックをオンのまま終了した場合に実行されます。",
            )

    def on_processing_settings_changed(self) -> None:
        self.persist_config()
        self.processed_cache.clear()
        self.prefetching_processed_keys.clear()
        self.prefetch_engine_done_paths.clear()
        self.prefetch_generation += 1
        if self.image_paths:
            self.display_current_image()

    def on_viewer_prefetch_changed(self) -> None:
        self.persist_config()
        self.auto_tune_pixmap_cache_limit()
        if self.image_paths:
            self.request_schedule_prefetch(0)

    def on_sort_mode_changed(self) -> None:
        self.config_data.sort_mode = self.sort_mode_combo.currentData() or "name"
        self.persist_config()
        if self.archive_mode_active() or not self.image_paths:
            return
        current_path = self.image_paths[self.current_index] if 0 <= self.current_index < len(self.image_paths) else None
        self.image_paths = sort_images(self.image_paths, mode=self.config_data.sort_mode)
        self.refresh_image_path_sets()
        if current_path is not None and current_path in self.image_paths:
            self.current_index = self.image_paths.index(current_path)
        self.update_page_position_slider()
        self.rebuild_thumbnail_items()

    def choose_engine_exe(self) -> None:
        engine = self.current_engine()
        title = f"{ENGINE_LABELS[engine]} exeを選択"
        path, _filter = QFileDialog.getOpenFileName(self, title, self.config_data.last_dir or str(APP_DIR), "Executable (*.exe);;All files (*.*)")
        if path:
            if engine == ENGINE_REALESRGAN:
                self.command_edit.setText(f'"{path}" -i "{{input}}" -o "{{output}}" -s {{scale}} -t {{tile}} -n {{model}}')
            else:
                self.command_edit.setText(f'"{path}" -i "{{input}}" -o "{{output}}" -s {{scale}} -n {{denoise}} -t {{tile}}')
            self.persist_config()

    def force_reprocess(self) -> None:
        if not self.image_paths:
            return
        path = self.image_paths[self.current_index]
        self.processed_cache.pop(self.processing_key(path), None)
        self.viewer.set_processed(None)
        self.enqueue_upscale(path, front=True, force=True)

    def refresh_engine_preset_combo(self) -> None:
        combo = getattr(self, "engine_preset_combo", None)
        if combo is None:
            return
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for name in sorted(self.config_data.engine_presets.keys(), key=str.casefold):
            combo.addItem(name, name)
        if current is not None:
            index = combo.findData(current)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def current_engine_preset_payload(self) -> dict[str, object]:
        return {
            "engine": self.current_engine(),
            "scale": int(self.scale_combo.currentText()),
            "denoise": int(self.denoise_combo.currentText()),
            "tile": self.tile_spin.value(),
            "model": self.realesrgan_model_combo.currentText(),
        }

    def save_current_engine_preset(self) -> None:
        default_name = f"{ENGINE_LABELS[self.current_engine()]} {self.scale_combo.currentText()}x"
        name, ok = QInputDialog.getText(self, APP_NAME, "プリセット名", text=default_name)
        if not ok:
            return
        preset_name = name.strip()
        if not preset_name:
            return
        self.config_data.engine_presets[preset_name] = self.current_engine_preset_payload()
        self.refresh_engine_preset_combo()
        index = self.engine_preset_combo.findData(preset_name)
        if index >= 0:
            self.engine_preset_combo.setCurrentIndex(index)
        self.persist_config()

    def load_selected_engine_preset(self) -> None:
        name = self.engine_preset_combo.currentData()
        if not isinstance(name, str):
            return
        preset = self.config_data.engine_presets.get(name)
        if not isinstance(preset, dict):
            return
        engine = str(preset.get("engine", self.current_engine()))
        if engine not in ENGINE_LABELS:
            engine = ENGINE_REALCUGAN
        self.engine_combo.setCurrentText(ENGINE_LABELS[engine])
        self.scale_combo.setCurrentText(str(preset.get("scale", 2)))
        self.denoise_combo.setCurrentText(str(preset.get("denoise", 0)))
        self.tile_spin.setValue(coerce_int(preset.get("tile", 0), 0))
        model = str(preset.get("model", self.realesrgan_model_combo.currentText()))
        model_index = self.realesrgan_model_combo.findText(model)
        if model_index >= 0:
            self.realesrgan_model_combo.setCurrentIndex(model_index)
        self.on_processing_settings_changed()

    def apply_recommended_model_preset(self) -> None:
        recommendations = {
            "realesr-animevideov3": {"engine": ENGINE_REALESRGAN, "scale": 4, "denoise": 0, "tile": 0, "model": "realesr-animevideov3"},
            "realesrgan-x4plus": {"engine": ENGINE_REALESRGAN, "scale": 4, "denoise": 0, "tile": 0, "model": "realesrgan-x4plus"},
            "realesrgan-x4plus-anime": {"engine": ENGINE_REALESRGAN, "scale": 4, "denoise": 0, "tile": 0, "model": "realesrgan-x4plus-anime"},
        }
        if self.current_engine() == ENGINE_REALCUGAN:
            self.scale_combo.setCurrentText("2")
            self.denoise_combo.setCurrentText("1")
            self.tile_spin.setValue(0)
            self.on_processing_settings_changed()
            return
        model = self.realesrgan_model_combo.currentText()
        preset = recommendations.get(model, recommendations["realesr-animevideov3"])
        self.scale_combo.setCurrentText(str(preset["scale"]))
        self.tile_spin.setValue(coerce_int(preset["tile"], 0))
        self.on_processing_settings_changed()

    def cancel_processing_jobs(self) -> None:
        with self.work_queue.mutex:
            pending = len(self.work_queue.queue)
            self.work_queue.queue.clear()
        self.queued_paths.clear()
        self.clear_prefetch_io_queue()
        self.prefetching_processed_keys.clear()
        self.prefetch_engine_plan = []
        self.append_log_with_level(f"Cancelled pending jobs: {pending}", LOG_LEVEL_WARN)
        self.status_label.setText("処理キューをキャンセルしました" if self.ui_language() != "en" else "Processing queue cancelled")

    def request_schedule_prefetch(self, delay_ms: int = PREFETCH_DEBOUNCE_MS) -> None:
        if not self.image_paths:
            return
        self.prefetch_timer.start(max(0, delay_ms))

    def clear_prefetch_io_queue(self) -> None:
        with self.prefetch_io_queue.mutex:
            self.prefetch_io_queue.queue.clear()

    def queue_prefetch_io_task(self, generation: int, priority: int, kind: str, key: object, source: str, target: str) -> None:
        with self.prefetch_io_lock:
            self.prefetch_io_sequence += 1
            sequence = self.prefetch_io_sequence
        self.prefetch_io_queue.put((int(priority), sequence, generation, kind, key, source, target))

    def _prefetch_io_worker_loop(self) -> None:
        while True:
            priority, sequence, generation, kind, key, source, target = self.prefetch_io_queue.get()
            if generation != self.prefetch_generation:
                continue
            started = time.perf_counter()
            originals: dict[Path, QImage] = {}
            processed: dict[ProcessingKey, QImage] = {}
            attempted_originals: list[Path] = []
            attempted_processed: list[ProcessingKey] = []
            if kind == "original":
                path = self.normalized_path(Path(source))
                attempted_originals.append(path)
                image = QImage(str(path))
                if not image.isNull():
                    originals[path] = image
                self.signals.profile_event.emit("元画像IO", (time.perf_counter() - started) * 1000)
            elif kind == "processed":
                processed_key = key
                if isinstance(processed_key, tuple):
                    attempted_processed.append(processed_key)
                    target_path = Path(target)
                    if target_path.exists():
                        image = QImage(str(target_path))
                        if not image.isNull():
                            processed[processed_key] = image
                    self.signals.profile_event.emit("拡大画像IO", (time.perf_counter() - started) * 1000)
            if originals or processed or attempted_originals or attempted_processed:
                self.signals.prefetch_done.emit(
                    generation,
                    originals,
                    processed,
                    attempted_originals,
                    attempted_processed,
                )

    def schedule_prefetch(self) -> None:
        if not self.image_paths:
            return
        self.prefetch_generation += 1
        self.prefetching_original_paths.clear()
        self.prefetching_processed_keys.clear()
        self.clear_prefetch_io_queue()
        realcugan_plan = self.make_plan(self.realcugan_prefetch_spin.value())
        viewer_plan = self.make_prefetch_plan(self.viewer_prefetch_spin.value())
        self.prefetch_viewer_plan = viewer_plan
        self.prefetch_engine_plan = realcugan_plan[1:]
        self.prefetch_engine_done_paths = {
            self.normalized_path(path)
            for path in self.prefetch_engine_plan
            if self.processing_key(path) in self.processed_cache
        }
        self.start_viewer_prefetch(viewer_plan)
        self.update_prefetch_progress_bars()
        for position, path in enumerate(realcugan_plan):
            self.enqueue_upscale(path, front=position == 0, check_existing=False, check_skip=False)
        self.reorder_work_queue(realcugan_plan)

    def start_viewer_prefetch(self, viewer_plan: list[Path]) -> None:
        if not viewer_plan:
            self.update_prefetch_progress_bars(viewer_plan)
            return
        generation = self.prefetch_generation
        before_originals = len(self.original_cache)
        before_processed = len(self.processed_cache)
        before_pixmaps = len(self.viewer.pixmap_cache)
        original_paths: list[Path] = []
        for path in viewer_plan:
            resolved = self.normalized_path(path)
            if resolved not in self.original_cache and resolved not in self.prefetching_original_paths:
                original_paths.append(resolved)
        processed_candidates: list[tuple[ProcessingKey, Path]] = []
        for path in viewer_plan:
            key = self.processing_key(path)
            if key in self.processed_cache or key in self.prefetching_processed_keys:
                continue
            if self.archive_mode_active() or not self.use_scale_cache_check.isChecked():
                continue
            processed_candidates.append((key, self.cache_output_path(path, create_dir=False)))
        if not original_paths and not processed_candidates:
            self.update_prefetch_progress_bars(viewer_plan)
            self.append_log_if_visible(
                f"Viewer prefetch: ready originals={before_originals}, processed={before_processed}, pixmaps={before_pixmaps}"
            )
            return
        self.prefetching_original_paths.update(original_paths)
        self.prefetching_processed_keys.update(key for key, _path in processed_candidates)
        self.update_prefetch_progress_bars(viewer_plan)
        self.append_log_if_visible(
            "Viewer prefetch start: "
            f"plan={len(viewer_plan)}, original_read={len(original_paths)}, processed_check={len(processed_candidates)}, "
            f"cache originals={before_originals}, processed={before_processed}, pixmaps={before_pixmaps}"
        )

        priority_rank = {self.normalized_path(path): index for index, path in enumerate(viewer_plan)}
        for path in original_paths:
            self.queue_prefetch_io_task(
                generation,
                priority_rank.get(self.normalized_path(path), len(priority_rank)),
                "original",
                path,
                str(path),
                "",
            )
        for key, processed_path in processed_candidates:
            source_path = self.normalized_path(Path(key[0]))
            self.queue_prefetch_io_task(
                generation,
                priority_rank.get(source_path, len(priority_rank)) + 1,
                "processed",
                key,
                key[0],
                str(processed_path),
            )

    def on_prefetch_done(
        self,
        generation: int,
        originals: dict[Path, QImage],
        processed: dict[ProcessingKey, QImage],
        attempted_originals: list[Path],
        attempted_processed: list[ProcessingKey],
    ) -> None:
        for path in attempted_originals:
            self.prefetching_original_paths.discard(path)
        for key in attempted_processed:
            self.prefetching_processed_keys.discard(key)
        if generation != self.prefetch_generation:
            return
        started = time.perf_counter()
        current_paths = self.image_path_set
        current_path_strings = self.image_path_string_set
        added_originals = 0
        with self.original_cache_lock:
            for path, image in originals.items():
                if path in current_paths and path not in self.original_cache:
                    self.original_cache[path] = image
                    added_originals += 1
            while len(self.original_cache) > max(6, self.config_data.viewer_prefetch_count * 2 + 3):
                self.original_cache.popitem(last=False)
        added_processed = 0
        engine_plan_paths = {self.normalized_path(path) for path in self.prefetch_engine_plan}
        for key, image in processed.items():
            if self.is_current_processing_key(key, current_path_strings) and key not in self.processed_cache:
                self.processed_cache[key] = image
                self._trim_processed_cache()
                added_processed += 1
            processed_source = self.normalized_path(Path(key[0]))
            if processed_source in engine_plan_paths:
                self.prefetch_engine_done_paths.add(processed_source)
        warm_items: list[tuple[object, QImage]] = [
            (self.pixmap_progress_key("original", path), image)
            for path, image in originals.items()
            if path in current_paths and not image.isNull()
        ]
        warm_items.extend(
            (self.pixmap_progress_key("processed", Path(key[0])), image)
            for key, image in processed.items()
            if self.is_current_processing_key(key, current_path_strings) and not image.isNull()
        )
        if warm_items:
            self.viewer.queue_pixmap_prefetch(warm_items)
        self.update_prefetch_progress_bars()
        if not self.prefetching_original_paths and not self.prefetching_processed_keys:
            self.append_log_if_visible(
                "Viewer prefetch done: "
                f"cache originals={len(self.original_cache)}, processed={len(self.processed_cache)}, "
                f"pixmaps={len(self.viewer.pixmap_cache)}"
            )
        self.record_profile("先読み反映(UI)", (time.perf_counter() - started) * 1000)

    def is_current_processing_key(self, key: ProcessingKey, current_paths: set[str] | None = None) -> bool:
        if len(key) != 6:
            return False
        current_paths = current_paths or self.image_path_string_set
        return (
            key[0] in current_paths
            and key[1] == self.current_engine()
            and key[2] == self.effective_scale()
            and key[3] == (int(self.denoise_combo.currentText()) if self.current_engine() == ENGINE_REALCUGAN else 0)
            and key[4] == self.tile_spin.value()
            and key[5] == (self.realesrgan_model_combo.currentText() if self.current_engine() == ENGINE_REALESRGAN else "")
        )

    def make_plan(self, count: int) -> list[Path]:
        if not self.image_paths or self.current_index < 0:
            return []
        plan = [self.image_paths[self.current_index]]
        predicted_step = self.pending_page_steps if self.pending_page_steps != 0 else self.last_navigation_step
        predicted_direction = 1 if predicted_step >= 0 else -1
        scored: list[tuple[int, int]] = []
        for index in range(len(self.image_paths)):
            if index == self.current_index:
                continue
            distance = abs(index - self.current_index)
            if distance > count:
                continue
            direction = 1 if index > self.current_index else -1
            score = distance * 4 + (0 if direction == predicted_direction else 1)
            scored.append((score, index))
        scored.sort(key=lambda item: item[0])
        for _score, index in scored:
            plan.append(self.image_paths[index])
        return plan

    def make_prefetch_plan(self, count: int) -> list[Path]:
        return self.make_plan(count)[1:]

    def enqueue_upscale(
        self,
        path: Path,
        front: bool = False,
        force: bool = False,
        check_existing: bool = True,
        check_skip: bool = True,
    ) -> None:
        path = self.normalized_path(path)
        if check_existing and not force and self.has_processed_result(path):
            return
        if check_skip and self.should_skip_upscale(path):
            return
        if path in self.processing_paths:
            return
        if path in self.queued_paths:
            if front:
                self.promote_work_item(path)
            return
        self.queued_paths.add(path)
        if front:
            with self.work_queue.mutex:
                self.work_queue.queue.appendleft(path)
                self.work_queue.unfinished_tasks += 1
                self.work_queue.not_empty.notify()
        else:
            self.work_queue.put(path)

    def promote_work_item(self, path: Path) -> None:
        with self.work_queue.mutex:
            items = [item for item in self.work_queue.queue if item != path]
            self.work_queue.queue.clear()
            self.work_queue.queue.extend(items)
            self.work_queue.queue.appendleft(path)
            self.work_queue.not_empty.notify()

    def reorder_work_queue(self, priority_paths: list[Path]) -> None:
        priority = [self.normalized_path(path) for path in priority_paths]
        priority_rank = {path: index for index, path in enumerate(priority)}
        with self.work_queue.mutex:
            items = [item for item in self.work_queue.queue if item is not None]
            if not items:
                return
            items.sort(key=lambda item: priority_rank.get(self.normalized_path(item), len(priority_rank) + 1))
            self.work_queue.queue.clear()
            self.work_queue.queue.extend(items)
            self.work_queue.not_empty.notify()

    def _worker_loop(self) -> None:
        while True:
            path = self.work_queue.get()
            if path is None or getattr(self, "closing", False):
                return
            self.queued_paths.discard(path)
            if self.has_processed_result(path):
                continue
            skip_enabled = self.config_data.skip_realcugan_for_tall_images
            height_threshold = self.config_data.skip_realcugan_height_threshold
            if self.should_skip_upscale_in_worker(path, skip_enabled, height_threshold):
                continue
            self.processing_paths.add(path)
            self.signals.process_started.emit(str(path))
            result = self.run_upscale_engine(path)
            self.processing_paths.discard(path)
            self.signals.process_done.emit(result)

    def should_skip_upscale_in_worker(self, path: Path, skip_enabled: bool, height_threshold: int) -> bool:
        if not skip_enabled:
            return False
        image = QImage(str(path))
        return not image.isNull() and image.height() >= height_threshold

    def run_upscale_engine(self, source: Path) -> dict:
        output_path, command_output_path, persist_output = self.prepare_output_path(source)
        values = {
            "input": str(source),
            "output": str(command_output_path),
            "scale": self.effective_scale(),
            "denoise": self.denoise_combo.currentText(),
            "tile": self.tile_spin.value(),
            "model": self.realesrgan_model_combo.currentText(),
        }
        try:
            command = format_command_template(self.active_command_template(), values)
        except ValueError as exc:
            return {
                "path": source,
                "code": 1,
                "output": f"Invalid command template: {exc}",
                "image": QImage(),
                "elapsed_ms": 0.0,
                "attempts": 1,
            }
        try:
            command_args = split_command_line(command)
        except ValueError as exc:
            return {
                "path": source,
                "code": 1,
                "output": f"Invalid command template: {exc}",
                "image": QImage(),
                "elapsed_ms": 0.0,
                "attempts": 1,
            }
        if not command_args:
            return {
                "path": source,
                "code": 1,
                "output": "Invalid command template: empty command",
                "image": QImage(),
                "elapsed_ms": 0.0,
                "attempts": 1,
            }
        attempts = max(1, int(self.config_data.engine_retry_count) + 1)
        started = time.perf_counter()
        outputs: list[str] = []
        for attempt in range(1, attempts + 1):
            try:
                 completed = subprocess.run(
                     command_args,
                     stdout=subprocess.PIPE,
                     stderr=subprocess.STDOUT,
                     shell=False,
                     cwd=str(self.command_working_dir(command)),
                     text=True,
                     encoding="utf-8",
                     errors="replace",
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     check=False,
                 )
            except Exception as exc:
                outputs.append(f"Attempt {attempt}/{attempts}: {exc}")
                if command_output_path.exists():
                    command_output_path.unlink(missing_ok=True)
                continue
            outputs.append(f"Attempt {attempt}/{attempts} exit={completed.returncode}")
            if completed.stdout.strip():
                outputs.append(completed.stdout.strip())
            if completed.returncode == 0:
                image = QImage(str(command_output_path)) if command_output_path.exists() else QImage()
                if not image.isNull():
                    if persist_output:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        command_output_path.replace(output_path)
                    else:
                        if command_output_path.exists():
                            command_output_path.unlink(missing_ok=True)
                    return {
                        "path": source,
                        "code": 0,
                        "output": "\n".join(outputs),
                        "image": image,
                        "elapsed_ms": (time.perf_counter() - started) * 1000,
                        "attempts": attempt,
                    }
            if command_output_path.exists():
                command_output_path.unlink(missing_ok=True)
        return {
            "path": source,
            "code": 1,
            "output": "\n".join(outputs),
            "image": QImage(),
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "attempts": attempts,
        }

    def on_process_started(self, path_text: str) -> None:
        path = Path(path_text)
        self.append_log(f"{self.engine_label()} started: {self.display_name(path)}")
        self.append_log_if_visible(f"Command preview: {self.build_engine_command_preview(path)}")
        self.append_log_if_visible(
            f"Progress: running={len(self.processing_paths)} queued={len(self.queued_paths)} cache={len(self.processed_cache)}"
        )
        self.update_window_title()

    def build_engine_command_preview(self, source: Path) -> str:
        values = {
            "input": str(source),
            "output": "<output>",
            "scale": self.effective_scale(),
            "denoise": self.denoise_combo.currentText(),
            "tile": self.tile_spin.value(),
            "model": self.realesrgan_model_combo.currentText(),
        }
        try:
            return format_command_template(self.active_command_template(), values)
        except ValueError as exc:
            return f"<invalid template: {exc}>"

    def on_process_done(self, result: dict) -> None:
        path: Path = result["path"]
        output = result.get("output") or ""
        if output:
            self.append_log(output)
        if result["code"] == 0 and not result["image"].isNull():
            self.record_profile(f"{self.engine_label()}処理", float(result.get("elapsed_ms", 0.0)))
            attempts = int(result.get("attempts", 1))
            if attempts > 1:
                self.append_log_with_level(f"Succeeded after retry attempts: {attempts}", LOG_LEVEL_WARN)
            self.append_log(
                f"Done: {self.display_name(path)} (elapsed={float(result.get('elapsed_ms', 0.0)):.1f}ms, attempts={attempts})"
            )
            key = self.processing_key(path)
            self.processed_cache[key] = result["image"]
            self._trim_processed_cache()
            self.prefetch_engine_done_paths.add(self.normalized_path(path))
            self.update_prefetch_progress_bars()
            if self.current_index >= 0 and self.normalized_path(path) == self.normalized_path(self.image_paths[self.current_index]):
                self.viewer.set_processed(result["image"])
                self.viewer.pixmap_prefetch_done_keys.add(self.pixmap_progress_key("processed", path))
                self.status_label.setText(f"{self.current_index + 1}/{len(self.image_paths)} 処理済み: {self.display_name(path)}")
                self.update_window_title()
        else:
            self.append_log_with_level(f"Process exited with code {result['code']}: {self.display_name(path)}", LOG_LEVEL_ERROR)
            self.update_prefetch_progress_bars()
        self.append_log_if_visible(
            f"Progress: running={len(self.processing_paths)} queued={len(self.queued_paths)} done_cache={len(self.processed_cache)}"
        )

    def has_processed_result(self, source: Path) -> bool:
        return self.processing_key(source) in self.processed_cache or self.existing_processed_path(source) is not None

    def existing_processed_path(self, source: Path) -> Path | None:
        if self.archive_mode_active() or not self.use_scale_cache_check.isChecked():
            return None
        path = self.cache_output_path(source, create_dir=False)
        return path if path.exists() else None

    def prepare_output_path(self, source: Path) -> tuple[Path, Path, bool]:
        if self.save_scale_check.isChecked() and not self.archive_mode_active():
            final_output = self.cache_output_path(source, create_dir=True)
            fd, text_path = tempfile.mkstemp(prefix=TEMP_OUTPUT_PREFIX, suffix=".png", dir=self.process_temp_dir)
            os.close(fd)
            return final_output, Path(text_path), True
        fd, text_path = tempfile.mkstemp(prefix=TEMP_OUTPUT_PREFIX, suffix=".png", dir=self.process_temp_dir)
        os.close(fd)
        temp_output = Path(text_path)
        return temp_output, temp_output, False

    def cache_output_path(self, source: Path, create_dir: bool) -> Path:
        engine_model = self.cache_model_name()
        folder_name = f"{engine_model}_x{self.effective_scale()}"
        folder = source.parent / folder_name
        if create_dir:
            folder.mkdir(parents=True, exist_ok=True)
        return folder / source.name

    def processing_key(self, source: Path) -> ProcessingKey:
        return (
            self.normalized_path_text(source),
            self.current_engine(),
            self.effective_scale(),
            int(self.denoise_combo.currentText()) if self.current_engine() == ENGINE_REALCUGAN else 0,
            self.tile_spin.value(),
            self.realesrgan_model_combo.currentText() if self.current_engine() == ENGINE_REALESRGAN else "",
        )

    def cache_model_name(self) -> str:
        if self.current_engine() == ENGINE_REALESRGAN:
            raw = f"realesrgan_{self.realesrgan_model_combo.currentText()}"
        else:
            raw = "realcugan"
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)

    def command_working_dir(self, command: str) -> Path:
        stripped = command.strip()
        exe = stripped[1:stripped.find('"', 1)] if stripped.startswith('"') and stripped.find('"', 1) > 1 else stripped.split(maxsplit=1)[0]
        exe_path = Path(exe)
        if exe_path.is_absolute() and exe_path.is_file():
            return exe_path.parent
        if (APP_DIR / exe_path).is_file():
            return APP_DIR
        return exe_path.parent if exe_path.is_file() else APP_DIR

    def collect_images(self, folder: Path) -> list[Path]:
        folder = folder.resolve()
        images: list[Path] = []
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    suffix = Path(entry.name).suffix.lower()
                    if suffix in IMAGE_EXTENSIONS:
                        images.append(folder / entry.name)
        except OSError:
            return []
        return sort_images(images, mode=self.config_data.sort_mode)

    def is_image(self, path: Path) -> bool:
        return path.suffix.lower() in IMAGE_EXTENSIONS

    def open_archive(self, archive_path: Path) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix=TEMP_ARCHIVE_PREFIX))
        self.write_temp_lock(temp_dir)
        try:
            images, names = self.extract_archive_images(archive_path, temp_dir)
        except ArchiveError as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            self.append_log_with_level(f"Archive open failed: {archive_path.name} | {exc}", LOG_LEVEL_ERROR)
            QMessageBox.critical(self, APP_NAME, self.archive_open_error_message(exc))
            return
        if not images:
            shutil.rmtree(temp_dir, ignore_errors=True)
            QMessageBox.information(self, APP_NAME, "このアーカイブには対応画像がありません。")
            return
        self.leave_archive_mode()
        self.archive_temp_dir = temp_dir
        self.archive_source_path = archive_path
        self.archive_display_names = names
        self.set_archive_options_enabled(False)
        self.set_image_list(images, 0)

    def open_pdf(self, pdf_path: Path) -> None:
        temp_dir = Path(tempfile.mkdtemp(prefix=TEMP_ARCHIVE_PREFIX))
        self.write_temp_lock(temp_dir)
        try:
            if QPdfDocument is None:
                raise ArchiveError("PDF support is unavailable.")
            document = QPdfDocument()
            document.load(str(pdf_path))
            if document.error() != QPdfDocument.Error.None_:
                raise ArchiveError("PDF decoder error")
            total_pages = document.pageCount()
            if total_pages <= 0:
                raise ArchiveError("PDF has no pages")

            first_page_path = _render_pdf_page_image(
                document,
                pdf_path,
                temp_dir,
                0,
                PDF_RENDER_SCALE,
                PDF_MAX_RENDER_PIXELS,
            )
        except ArchiveError as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            self.append_log_with_level(f"PDF open failed: {pdf_path.name} | {exc}", LOG_LEVEL_ERROR)
            QMessageBox.critical(self, APP_NAME, self.tr_ui("PDFを開けませんでした。"))
            return

        first_page_name = f"{pdf_path.name} [page 1]"
        images = [first_page_path]
        names = {first_page_path.resolve(): first_page_name}
        self.leave_archive_mode()
        self.archive_temp_dir = temp_dir
        self.archive_source_path = pdf_path
        self.archive_display_names = names
        self.set_archive_options_enabled(False)
        self.set_image_list(images, 0)
        self.runtime_state.pdf_expected_pages = total_pages
        self.runtime_state.pdf_loaded_pages = 1

        if total_pages > 1:
            session_id = self.runtime_state.pdf_load_session_id
            self.runtime_state.pdf_loading = True
            self.append_log_if_visible(f"PDF background expansion started: 1/{total_pages}")
            self.start_pdf_background_render(pdf_path, temp_dir, 1, total_pages, session_id)

    def extract_archive_images(self, archive_path: Path, temp_dir: Path) -> tuple[list[Path], ArchiveDisplayMap]:
        return extract_archive_images_impl(archive_path, temp_dir, self.is_image, py7zr, rarfile)

    def extract_zip_images(self, archive_path: Path, temp_dir: Path) -> tuple[list[Path], ArchiveDisplayMap]:
        return extract_zip_images_impl(archive_path, temp_dir, self.is_image)

    def extract_rar_images(self, archive_path: Path, temp_dir: Path) -> tuple[list[Path], ArchiveDisplayMap]:
        if rarfile is None:
            return extract_with_7z_command_impl(archive_path, temp_dir, self.is_image)
        return extract_rar_images_impl(archive_path, temp_dir, self.is_image, rarfile)

    def extract_with_7z_command(self, archive_path: Path, temp_dir: Path) -> tuple[list[Path], ArchiveDisplayMap]:
        return extract_with_7z_command_impl(archive_path, temp_dir, self.is_image)

    def archive_open_error_message(self, error: Exception) -> str:
        return build_archive_open_error_message(error, self.ui_language())

    def collect_archive_outputs(self, temp_dir: Path) -> tuple[list[Path], ArchiveDisplayMap]:
        return collect_extracted_archive_outputs(temp_dir, self.is_image)

    def find_7z(self) -> Path | None:
        return find_7z_command()

    def archive_member_output_path(self, temp_dir: Path, member_name: str) -> Path | None:
        return build_archive_member_output_path(temp_dir, member_name)

    def archive_display_name(self, member_name: str) -> str:
        return archive_display_name(member_name)

    def archive_mode_active(self) -> bool:
        return self.archive_temp_dir is not None

    def set_archive_options_enabled(self, enabled: bool) -> None:
        if not enabled and self.archive_disabled_scale_options is None:
            self.archive_disabled_scale_options = (self.save_scale_check.isChecked(), self.use_scale_cache_check.isChecked())
        self.save_scale_check.setEnabled(enabled)
        self.use_scale_cache_check.setEnabled(enabled)
        self.archive_help.setVisible(not enabled)
        if not enabled:
            self.save_scale_check.blockSignals(True)
            self.use_scale_cache_check.blockSignals(True)
            self.save_scale_check.setChecked(False)
            self.use_scale_cache_check.setChecked(False)
            self.save_scale_check.blockSignals(False)
            self.use_scale_cache_check.blockSignals(False)
        elif self.archive_disabled_scale_options is not None:
            save_enabled, cache_enabled = self.archive_disabled_scale_options
            self.archive_disabled_scale_options = None
            self.save_scale_check.blockSignals(True)
            self.use_scale_cache_check.blockSignals(True)
            self.save_scale_check.setChecked(save_enabled)
            self.use_scale_cache_check.setChecked(cache_enabled)
            self.save_scale_check.blockSignals(False)
            self.use_scale_cache_check.blockSignals(False)

    def leave_archive_mode(self) -> None:
        if self.archive_temp_dir:
            self.retired_archive_temp_dirs.append(self.archive_temp_dir)
        self.archive_temp_dir = None
        self.archive_source_path = None
        self.archive_display_names.clear()
        self.set_archive_options_enabled(True)

    def display_name(self, path: Path) -> str:
        return self.archive_display_names.get(path.resolve(), path.name)

    def write_temp_lock(self, temp_dir: Path) -> None:
        try:
            (temp_dir / TEMP_LOCK_FILE).write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass

    def _cleanup_stale_temp_files(self) -> tuple[int, list[str]]:
        return cleanup_stale_temp_entries(
            Path(tempfile.gettempdir()),
            TEMP_ARCHIVE_PREFIX,
            TEMP_WORK_PREFIX,
            TEMP_OUTPUT_PREFIX,
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing = True
        self._show_fullscreen_cursor()
        self.persist_config()
        self.work_queue.put(None)
        paths = list(self.retired_archive_temp_dirs)
        if self.archive_temp_dir:
            paths.append(self.archive_temp_dir)
        if self.process_temp_dir:
            paths.append(self.process_temp_dir)
        for path in paths:
            shutil.rmtree(path, ignore_errors=True)
        super().closeEvent(event)

    def on_copy_debug_info(self) -> None:
        lines = [
            f"App: {APP_NAME}",
            f"Python: {sys.version.split()[0]}",
            f"OS: {os.name}",
            f"Engine: {self.current_engine()}",
            f"Scale: {self.effective_scale()}",
            f"Denoise: {self.denoise_combo.currentText()}",
            f"Tile: {self.tile_spin.value()}",
            f"Model: {self.realesrgan_model_combo.currentText()}",
            f"RetryCount: {self.engine_retry_spin.value()}",
            f"ImageCount: {len(self.image_paths)}",
            f"CurrentIndex: {self.current_index}",
            f"ArchiveMode: {self.archive_mode_active()}",
            f"LogLevel: {self.log_level()}",
            f"ConfigPath: {CONFIG_PATH}",
        ]
        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        self.append_log_if_visible(text)
        self.status_label.setText(self.tr_ui("デバッグ情報をクリップボードへコピーしました。"))

    def save_view_snapshot(self) -> None:
        self.view_snapshots["default"] = {
            "zoom": float(self.viewer.zoom),
            "offset_x": int(self.viewer.offset.x()),
            "offset_y": int(self.viewer.offset.y()),
            "rotation": int(self.viewer.display_rotation),
            "flip_h": bool(self.viewer.display_flip_horizontal),
            "flip_v": bool(self.viewer.display_flip_vertical),
        }
        self.append_log_if_visible("Saved view snapshot")

    def restore_view_snapshot(self) -> None:
        snapshot = self.view_snapshots.get("default")
        if not snapshot:
            return
        self.viewer.display_rotation = coerce_int(snapshot.get("rotation", 0), 0)
        self.viewer.display_flip_horizontal = bool(snapshot.get("flip_h", False))
        self.viewer.display_flip_vertical = bool(snapshot.get("flip_v", False))
        self.viewer.rebuild_display_images()
        self.viewer.zoom = self.viewer.clamp_zoom_factor(coerce_float(snapshot.get("zoom", 1.0), 1.0))
        self.viewer.offset = QPoint(coerce_int(snapshot.get("offset_x", 0), 0), coerce_int(snapshot.get("offset_y", 0), 0))
        self.viewer.update()
        self.append_log_if_visible("Restored view snapshot")

    def export_config_file(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(self, "Export config", str(APP_DIR / "setting-export.json"), "JSON (*.json)")
        if not path:
            return
        self.persist_config()
        try:
            Path(path).write_text(CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            self.append_log_if_visible(f"Config exported: {path}")
        except OSError as exc:
            self.append_log_with_level(f"Config export failed: {exc}", LOG_LEVEL_ERROR)

    def import_config_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Import config", self.config_data.last_dir or str(APP_DIR), "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            merged = AppConfig(**{**asdict(self.config_data), **data})
            merged.key_bindings = normalize_key_bindings(getattr(merged, "key_bindings", None))
            save_config(merged)
            self.append_log_if_visible(f"Config imported: {path}")
            QMessageBox.information(self, APP_NAME, "設定を読み込みました。再起動で完全反映されます。")
        except Exception as exc:
            self.append_log_with_level(f"Config import failed: {exc}", LOG_LEVEL_ERROR)

    def build_environment_diagnostics(self) -> str:
        lines = [
            f"AppDir: {APP_DIR}",
            f"ConfigPath: {CONFIG_PATH}",
            f"Python: {sys.version}",
            f"Engine(Current): {self.current_engine()}",
            f"Real-CUGAN exe: {self.executable_from_template(self.config_data.realcugan_command_template)}",
            f"Real-ESRGAN exe: {self.executable_from_template(self.config_data.realesrgan_command_template)}",
            f"py7zr: {'ok' if py7zr is not None else 'missing'}",
            f"rarfile: {'ok' if rarfile is not None else 'missing'}",
            f"OpenCV: {'ok' if cv2 is not None else 'missing'}",
            f"7z command: {self.find_7z()}",
        ]
        return "\n".join(lines)

    def on_show_diagnostics(self) -> None:
        text = self.build_environment_diagnostics()
        self.append_log_if_visible(text)
        QMessageBox.information(self, APP_NAME, text)


def main() -> None:
    parser = argparse.ArgumentParser(prog="raiv", add_help=True)
    parser.add_argument("path", nargs="?", default="", help="Image, folder, or archive path to open on startup")
    parser.add_argument("--lang", choices=["ja", "en"], default="", help="Force UI language")
    args = parser.parse_args()

    enable_high_dpi_awareness()
    set_process_app_user_model_id()

    def persist_crash_report(exc_type, exc_value, exc_tb) -> None:
        try:
            crash_dir = APP_DIR / "crash-reports"
            crash_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            report_path = crash_dir / f"crash-{stamp}.log"
            text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            report_path.write_text(text, encoding="utf-8")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = persist_crash_report

    app = QApplication([])
    app.setApplicationName(APP_NAME)
    if APP_ICON_ICO.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_ICO)))
    window = MainWindow(initial_path=args.path, forced_language=args.lang)
    window.show()
    window.raise_()
    window.activateWindow()
    QTimer.singleShot(0, window.raise_)
    QTimer.singleShot(0, window.activateWindow)
    app.exec()


if __name__ == "__main__":
    main()

